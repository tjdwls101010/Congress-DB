"""bill_relations 대안 관계 적재."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Literal, Sequence

RelationFetchMode = Literal["all", "missing"]

import requests
from bs4 import BeautifulSoup

from ..core.db import execute_many, get_conn
from ..core.progress import ProgressReporter, safe_print
from ..core.throttle import cap_worker_count, external_http_slot

LIKMS_DETAIL_URL = "https://likms.assembly.go.kr/bill/billDetail.do"
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
    proc_result: str | None
    cmt_proc_result: str | None = None

    @property
    def relation_type(self) -> str:
        # 본회의 처리결과가 폐기값이면 그것으로, 아니면 소관위-종료 원안(C1)이라
        # 위원회 처리결과(cmt_proc_result)에서 파생한다. 선정 SQL이 둘 중 하나는
        # 폐기값임을 보장한다.
        if self.proc_result in _PROC_TO_RELATION_TYPE:
            return _relation_type_for_proc_result(self.proc_result)
        return _relation_type_for_proc_result(self.cmt_proc_result)


@dataclass(frozen=True)
class _FetchedBillRelation:
    absorbed_bill_id: str
    alternative_bill_id: str
    relation_type: str


class MissingSelRefBillId(RuntimeError):
    """likms 상세페이지에 selRefBillId가 없는 경우."""


_UPSERT_BILL_RELATION_SQL = """
    INSERT INTO bill_relations (
        absorbed_bill_id, alternative_bill_id, relation_type
    )
    VALUES (
        %(absorbed_bill_id)s, %(alternative_bill_id)s, %(relation_type)s
    )
    ON CONFLICT (absorbed_bill_id) DO UPDATE SET
        alternative_bill_id = EXCLUDED.alternative_bill_id,
        relation_type       = EXCLUDED.relation_type,
        fetched_at          = now()
"""


def ingest_bill_relations(
    *,
    limit: int | None = None,
    worker_count: int = DEFAULT_WORKER_COUNT,
    retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
    relation_fetch_mode: RelationFetchMode = "all",
) -> IngestBillRelationsResult:
    """대안반영폐기/수정안반영폐기 원안의 흡수 대안 관계를 적재한다.

    relation_fetch_mode="missing"은 아직 bill_relations 행이 없는 원안만 스크랩한다(증분용) —
    전량 3,700여 건을 매일 재스크랩하는 것은 최취약 likms 경로에 과부하라 금지한다.
    선정 대상엔 본회의 폐기(proc_result)뿐 아니라 소관위-종료 폐기(proc_result NULL·cmt_proc_result
    폐기, C1)도 포함한다.
    """
    targets = _load_bill_relation_targets(
        limit=limit, relation_fetch_mode=relation_fetch_mode
    )
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


def _load_bill_relation_targets(
    *,
    limit: int | None = None,
    relation_fetch_mode: RelationFetchMode = "all",
) -> list[_BillRelationTarget]:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    if relation_fetch_mode not in ("all", "missing"):
        raise ValueError("relation_fetch_mode must be one of: all, missing")
    missing_only_sql = ""
    if relation_fetch_mode == "missing":
        missing_only_sql = (
            "AND NOT EXISTS (SELECT 1 FROM bill_relations r "
            "WHERE r.absorbed_bill_id = b.bill_id)"
        )
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT b.bill_id, b.proc_result, b.cmt_proc_result
            FROM bills b
            WHERE (
                    b.proc_result IN ('대안반영폐기', '수정안반영폐기')
                    OR (
                        b.proc_result IS NULL
                        AND b.cmt_proc_result IN ('대안반영폐기', '수정안반영폐기')
                    )
                  )
              {missing_only_sql}
            ORDER BY b.propose_dt DESC NULLS LAST, b.bill_no
            LIMIT %s
            """,
            (limit,),
        )
        return [
            _BillRelationTarget(
                bill_id=str(row[0]),
                proc_result=row[1],
                cmt_proc_result=row[2],
            )
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


def _relation_type_for_proc_result(proc_result: str | None) -> str:
    try:
        return _PROC_TO_RELATION_TYPE[proc_result]
    except KeyError as exc:
        raise ValueError(f"unsupported relation proc_result: {proc_result}") from exc
