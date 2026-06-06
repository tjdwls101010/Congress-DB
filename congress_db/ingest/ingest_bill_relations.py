"""bill_relations 대안 관계 적재."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Sequence

import requests
from bs4 import BeautifulSoup

from ..core.db import execute_many, get_conn
from ..core.progress import ProgressReporter, safe_print
from ..core.throttle import cap_worker_count, external_http_slot

LIKMS_DETAIL_URL = "https://likms.assembly.go.kr/bill/billDetail.do"
SOURCE = "likms_selrefbillid"
DEFAULT_WORKER_COUNT = 20
DEFAULT_RETRY_DELAYS = (1.0, 4.0, 16.0)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_PROC_TO_RELATION_TYPE = {
    "대안반영폐기": "대안반영",
    "수정안반영폐기": "수정안반영",
}


@dataclass(frozen=True)
class IngestBillRelationsResult:
    """bill_relations 적재 결과."""

    target_count: int
    relation_count: int
    upserted_count: int
    selected_worker_count: int
    failure_count: int
    failures: tuple["BillRelationFailure", ...]


@dataclass(frozen=True)
class BillRelationFailure:
    """대안 관계 fetch/검증 최종 실패."""

    bill_id: str
    reason: str
    error: str


@dataclass(frozen=True)
class _BillRelationTarget:
    bill_id: str
    proc_result: str

    @property
    def relation_type(self) -> str:
        return _relation_type_for_proc_result(self.proc_result)


@dataclass(frozen=True)
class _FetchedBillRelation:
    absorbed_bill_id: str
    alternative_bill_id: str
    relation_type: str
    source: str = SOURCE


class MissingSelRefBillId(RuntimeError):
    """likms 상세페이지에 selRefBillId가 없는 경우."""


_UPSERT_BILL_RELATION_SQL = """
    INSERT INTO bill_relations (
        absorbed_bill_id, alternative_bill_id, relation_type, source
    )
    VALUES (
        %(absorbed_bill_id)s, %(alternative_bill_id)s, %(relation_type)s, %(source)s
    )
    ON CONFLICT (absorbed_bill_id) DO UPDATE SET
        alternative_bill_id = EXCLUDED.alternative_bill_id,
        relation_type       = EXCLUDED.relation_type,
        source              = EXCLUDED.source,
        fetched_at          = now()
"""


def ingest_bill_relations(
    *,
    limit: int | None = None,
    worker_count: int = DEFAULT_WORKER_COUNT,
    retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
) -> IngestBillRelationsResult:
    """대안반영폐기/수정안반영폐기 원안의 흡수 대안 관계를 적재한다."""
    targets = _load_bill_relation_targets(limit=limit)
    selected_worker_count = cap_worker_count(worker_count) if targets else 0
    fetched, failures = _fetch_bill_relations(
        targets,
        worker_count=selected_worker_count,
        retry_delays=tuple(retry_delays),
    )
    rows = [
        {
            "absorbed_bill_id": relation.absorbed_bill_id,
            "alternative_bill_id": relation.alternative_bill_id,
            "relation_type": relation.relation_type,
            "source": relation.source,
        }
        for relation in fetched
    ]
    with get_conn() as conn:
        upserted_count = execute_many(conn, _UPSERT_BILL_RELATION_SQL, rows)
        _resolve_existing_dead_letters(
            conn,
            [relation.absorbed_bill_id for relation in fetched],
        )
        conn.commit()

    return IngestBillRelationsResult(
        target_count=len(targets),
        relation_count=len(fetched),
        upserted_count=upserted_count,
        selected_worker_count=selected_worker_count,
        failure_count=len(failures),
        failures=tuple(failures),
    )


def _load_bill_relation_targets(*, limit: int | None = None) -> list[_BillRelationTarget]:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bill_id, proc_result
            FROM bills
            WHERE proc_result IN ('대안반영폐기', '수정안반영폐기')
            ORDER BY propose_dt DESC NULLS LAST, bill_no
            LIMIT %s
            """,
            (limit,),
        )
        return [
            _BillRelationTarget(bill_id=str(row[0]), proc_result=str(row[1]))
            for row in cur.fetchall()
        ]


def _fetch_bill_relations(
    targets: list[_BillRelationTarget],
    *,
    worker_count: int,
    retry_delays: tuple[float, ...],
) -> tuple[list[_FetchedBillRelation], tuple[BillRelationFailure, ...]]:
    if not targets:
        return [], ()
    relations: list[_FetchedBillRelation] = []
    failures: list[BillRelationFailure] = []
    progress = ProgressReporter("bill relations", len(targets))
    progress.start()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(
                _fetch_bill_relation_with_retry,
                target,
                retry_delays=retry_delays,
            ): target
            for target in targets
        }
        for future in as_completed(futures):
            target = futures[future]
            try:
                relations.append(future.result())
                progress.advance()
            except MissingSelRefBillId as exc:
                failures.append(
                    BillRelationFailure(
                        bill_id=target.bill_id,
                        reason="missing_selref",
                        error=str(exc),
                    )
                )
                progress.advance(errors=1)
            except Exception as exc:  # noqa: BLE001 - item failure is preserved
                failures.append(
                    BillRelationFailure(
                        bill_id=target.bill_id,
                        reason="fetch_failed",
                        error=str(exc),
                    )
                )
                progress.advance(errors=1)
    progress.finish()
    return relations, tuple(failures)


def _fetch_bill_relation_with_retry(
    target: _BillRelationTarget,
    *,
    retry_delays: tuple[float, ...],
) -> _FetchedBillRelation:
    attempts = 0
    while True:
        attempts += 1
        try:
            return _fetch_bill_relation(target)
        except MissingSelRefBillId:
            raise
        except Exception as exc:
            if attempts > len(retry_delays):
                raise RuntimeError(f"after {attempts} attempts: {exc}") from exc
            delay = retry_delays[attempts - 1]
            safe_print(
                f"[retry] bill_relations bill_id={target.bill_id} "
                f"attempt={attempts} next_delay={delay:.1f}s error={exc}",
                flush=True,
            )
            if delay:
                time.sleep(delay)


def _fetch_bill_relation(target: _BillRelationTarget) -> _FetchedBillRelation:
    html = _fetch_likms_bill_detail(target.bill_id)
    alternative_bill_id = _parse_selref_bill_id(html)
    if not alternative_bill_id:
        raise MissingSelRefBillId(f"selRefBillId missing for {target.bill_id}")
    return _FetchedBillRelation(
        absorbed_bill_id=target.bill_id,
        alternative_bill_id=alternative_bill_id,
        relation_type=target.relation_type,
    )


def _fetch_likms_bill_detail(bill_id: str, *, timeout: int = 30) -> str:
    with external_http_slot():
        response = requests.get(
            LIKMS_DETAIL_URL,
            params={"billId": bill_id, "ageFrom": "22", "ageTo": "22"},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return response.text


def _parse_selref_bill_id(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    field = soup.find("input", id="selRefBillId")
    if field is None:
        return None
    value = str(field.get("value") or "").strip()
    return value or None


def _resolve_existing_dead_letters(conn: Any, absorbed_bill_ids: Sequence[str]) -> int:
    unique_ids = sorted({bill_id for bill_id in absorbed_bill_ids if bill_id})
    if not unique_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE dead_letters
            SET status = 'resolved',
                resolved_at = now()
            WHERE source = 'bill_relations'
              AND stage = 'bill_relations'
              AND item_key = ANY(%s)
              AND status IN ('pending', 'retrying', 'blocked')
            """,
            (unique_ids,),
        )
        return int(cur.rowcount)


def _relation_type_for_proc_result(proc_result: str) -> str:
    try:
        return _PROC_TO_RELATION_TYPE[proc_result]
    except KeyError as exc:
        raise ValueError(f"unsupported relation proc_result: {proc_result}") from exc
