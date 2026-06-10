"""bill_relations source id를 canonical bill row로 해소한다."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Sequence

from bs4 import BeautifulSoup

from ..core.db import get_conn
from ..core.progress import safe_print
from .ingest_bill_relations import _fetch_likms_bill_detail

SOURCE = "likms_billdetail"
DEFAULT_RETRY_DELAYS = (1.0, 4.0, 16.0)


@dataclass(frozen=True)
class BillSourceAliasTarget:
    """`bills`에 직접 없는 bill_relations target source id."""

    source_bill_id: str
    relation_types: tuple[str, ...]
    n_relations: int


@dataclass(frozen=True)
class BillSourceAlias:
    """해소되어 upsert된 source alias."""

    source_bill_id: str
    bill_no: str
    canonical_bill_id: str
    relation_types: tuple[str, ...]
    n_relations: int


@dataclass(frozen=True)
class BillSourceAliasGap:
    """정상적으로 남기는 미해소 source id."""

    source_bill_id: str
    bill_no: str | None
    reason: str
    relation_types: tuple[str, ...]
    n_relations: int


@dataclass(frozen=True)
class BillSourceAliasAmbiguity:
    """BILL_NO가 복수 canonical 후보에 닿아 추측하면 안 되는 경우."""

    source_bill_id: str
    bill_no: str
    canonical_bill_ids: tuple[str, ...]
    relation_types: tuple[str, ...]
    n_relations: int


@dataclass(frozen=True)
class BillSourceAliasFailure:
    """likms fetch 최종 실패."""

    source_bill_id: str
    reason: str
    error: str
    relation_types: tuple[str, ...]
    n_relations: int


@dataclass(frozen=True)
class BillSourceAliasBackfillResult:
    """bill_source_aliases 해소 결과."""

    target_count: int
    target_relation_count: int
    fetched_count: int
    alias_count: int
    alias_relation_count: int
    accepted_gap_count: int
    accepted_gap_relation_count: int
    ambiguous_count: int
    failure_count: int
    aliases: tuple[BillSourceAlias, ...]
    accepted_gaps: tuple[BillSourceAliasGap, ...]
    ambiguities: tuple[BillSourceAliasAmbiguity, ...]
    failures: tuple[BillSourceAliasFailure, ...]


@dataclass(frozen=True)
class _FetchedBillNo:
    target: BillSourceAliasTarget
    bill_no: str | None


_UPSERT_ALIAS_SQL = """
    INSERT INTO bill_source_aliases (
        source, source_bill_id, bill_no, canonical_bill_id
    )
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (source, source_bill_id) DO UPDATE SET
        bill_no           = EXCLUDED.bill_no,
        canonical_bill_id = EXCLUDED.canonical_bill_id,
        fetched_at        = now()
"""


def resolve_bill_source_aliases(
    *,
    limit: int | None = None,
    source_bill_ids: Sequence[str] | None = None,
    retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
) -> BillSourceAliasBackfillResult:
    """missing `alternative_bill_id`를 BILL_NO 경유 canonical bill로 해소한다."""
    targets = _load_missing_source_targets(limit=limit, source_bill_ids=source_bill_ids)
    fetched: list[_FetchedBillNo] = []
    failures: list[BillSourceAliasFailure] = []

    for target in targets:
        try:
            fetched.append(
                _FetchedBillNo(
                    target=target,
                    bill_no=_fetch_bill_no_with_retry(
                        target.source_bill_id,
                        retry_delays=tuple(retry_delays),
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001 - item failure is preserved
            failures.append(
                BillSourceAliasFailure(
                    source_bill_id=target.source_bill_id,
                    reason="fetch_failed",
                    error=str(exc),
                    relation_types=target.relation_types,
                    n_relations=target.n_relations,
                )
            )

    aliases, accepted_gaps, ambiguities = _resolve_fetched_bill_nos(fetched)
    return BillSourceAliasBackfillResult(
        target_count=len(targets),
        target_relation_count=sum(target.n_relations for target in targets),
        fetched_count=len(fetched),
        alias_count=len(aliases),
        alias_relation_count=sum(alias.n_relations for alias in aliases),
        accepted_gap_count=len(accepted_gaps),
        accepted_gap_relation_count=sum(gap.n_relations for gap in accepted_gaps),
        ambiguous_count=len(ambiguities),
        failure_count=len(failures),
        aliases=tuple(aliases),
        accepted_gaps=tuple(accepted_gaps),
        ambiguities=tuple(ambiguities),
        failures=tuple(failures),
    )


def _load_missing_source_targets(
    *,
    limit: int | None = None,
    source_bill_ids: Sequence[str] | None = None,
) -> list[BillSourceAliasTarget]:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    target_ids = None
    if source_bill_ids is not None:
        target_ids = sorted({str(source_bill_id) for source_bill_id in source_bill_ids})
        if not target_ids:
            return []
    source_filter = ""
    params: list[object] = []
    if target_ids is not None:
        source_filter = "AND r.alternative_bill_id = ANY(%s)"
        params.append(target_ids)
    params.append(limit)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                r.alternative_bill_id,
                array_agg(DISTINCT r.relation_type ORDER BY r.relation_type),
                count(*)::int
            FROM bill_relations r
            LEFT JOIN bills b ON b.bill_id = r.alternative_bill_id
            WHERE b.bill_id IS NULL
              {source_filter}
            GROUP BY r.alternative_bill_id
            ORDER BY min(r.relation_type), r.alternative_bill_id
            LIMIT %s
            """,
            params,
        )
        return [
            BillSourceAliasTarget(
                source_bill_id=str(row[0]),
                relation_types=tuple(str(value) for value in row[1]),
                n_relations=int(row[2]),
            )
            for row in cur.fetchall()
        ]


def _fetch_bill_no_with_retry(
    source_bill_id: str,
    *,
    retry_delays: tuple[float, ...],
) -> str | None:
    attempts = 0
    while True:
        attempts += 1
        try:
            return _fetch_bill_no(source_bill_id)
        except Exception as exc:
            if attempts > len(retry_delays):
                raise RuntimeError(f"after {attempts} attempts: {exc}") from exc
            delay = retry_delays[attempts - 1]
            safe_print(
                f"[retry] bill_source_aliases source_bill_id={source_bill_id} "
                f"attempt={attempts} next_delay={delay:.1f}s error={exc}",
                flush=True,
            )
            if delay:
                time.sleep(delay)


def _fetch_bill_no(source_bill_id: str) -> str | None:
    html = _fetch_likms_bill_detail(source_bill_id)
    return _parse_bill_no(html)


def _parse_bill_no(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    field = soup.find("input", id="billNo")
    if field is None:
        return None
    value = str(field.get("value") or "").strip()
    return value or None


def _resolve_fetched_bill_nos(
    fetched: Sequence[_FetchedBillNo],
) -> tuple[
    list[BillSourceAlias],
    list[BillSourceAliasGap],
    list[BillSourceAliasAmbiguity],
]:
    aliases: list[BillSourceAlias] = []
    accepted_gaps: list[BillSourceAliasGap] = []
    ambiguities: list[BillSourceAliasAmbiguity] = []
    if not fetched:
        return aliases, accepted_gaps, ambiguities

    with get_conn() as conn:
        for item in fetched:
            target = item.target
            if not item.bill_no:
                accepted_gaps.append(
                    BillSourceAliasGap(
                        source_bill_id=target.source_bill_id,
                        bill_no=None,
                        reason="missing_bill_no",
                        relation_types=target.relation_types,
                        n_relations=target.n_relations,
                    )
                )
                continue

            canonical_bill_ids = _load_canonical_bill_ids(conn, item.bill_no)
            if not canonical_bill_ids:
                accepted_gaps.append(
                    BillSourceAliasGap(
                        source_bill_id=target.source_bill_id,
                        bill_no=item.bill_no,
                        reason="missing_canonical_bill",
                        relation_types=target.relation_types,
                        n_relations=target.n_relations,
                    )
                )
                continue
            if len(canonical_bill_ids) > 1:
                ambiguities.append(
                    BillSourceAliasAmbiguity(
                        source_bill_id=target.source_bill_id,
                        bill_no=item.bill_no,
                        canonical_bill_ids=tuple(canonical_bill_ids),
                        relation_types=target.relation_types,
                        n_relations=target.n_relations,
                    )
                )
                continue

            alias = BillSourceAlias(
                source_bill_id=target.source_bill_id,
                bill_no=item.bill_no,
                canonical_bill_id=canonical_bill_ids[0],
                relation_types=target.relation_types,
                n_relations=target.n_relations,
            )
            _upsert_alias(conn, alias)
            aliases.append(alias)
        conn.commit()

    return aliases, accepted_gaps, ambiguities


def _load_canonical_bill_ids(conn: Any, bill_no: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_id
            FROM bills
            WHERE bill_no = %s
            ORDER BY bill_id
            """,
            (bill_no,),
        )
        return [str(row[0]) for row in cur.fetchall()]


def _upsert_alias(conn: Any, alias: BillSourceAlias) -> None:
    with conn.cursor() as cur:
        cur.execute(
            _UPSERT_ALIAS_SQL,
            (
                SOURCE,
                alias.source_bill_id,
                alias.bill_no,
                alias.canonical_bill_id,
            ),
        )
