"""ALLBILL 기반 최종 처리·공포 이력 백필."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..core.api_client import ApiResponse, fetch_endpoint
from ..core.db import execute_many, get_conn
from ..core.progress import ProgressReporter

ALLBILL_ENDPOINT = "ALLBILL"
OUTCOME_SOURCE = "allbill"
PASSED_PROC_RESULTS = frozenset({"원안가결", "수정가결"})

FetchAllbill = Callable[..., ApiResponse]


@dataclass(frozen=True)
class BillFinalOutcomeTarget:
    """ALLBILL 조회 대상 법안."""

    bill_id: str
    bill_no: str
    propose_dt: date | None
    proc_result: str | None
    has_outcome: bool

    @property
    def is_passed(self) -> bool:
        return self.proc_result in PASSED_PROC_RESULTS


@dataclass(frozen=True)
class BillFinalOutcomeFailure:
    """ALLBILL 단일 BILL_NO 조회 실패."""

    bill_id: str
    bill_no: str
    proc_result: str | None
    reason: str
    error: str


@dataclass(frozen=True)
class BillFinalOutcomesBackfillResult:
    """ALLBILL 최종 처리·공포 이력 백필 결과."""

    target_count: int
    skipped_count: int
    fetch_target_count: int
    fetched_count: int
    outcome_target_count: int
    outcome_upserted_count: int
    propose_dt_updated_count: int
    accepted_gap_count: int
    no_data_count: int
    error_count: int
    failures: tuple[BillFinalOutcomeFailure, ...]


@dataclass(frozen=True)
class _FetchedAllbillRow:
    target: BillFinalOutcomeTarget
    row: dict[str, Any]


_UPSERT_OUTCOME_SQL = """
    INSERT INTO bill_final_outcomes (
        bill_no, plenary_dt, govt_transfer_dt, promulgation_dt,
        prom_no, prom_law_nm, source
    )
    VALUES (
        %(bill_no)s, %(plenary_dt)s, %(govt_transfer_dt)s, %(promulgation_dt)s,
        %(prom_no)s, %(prom_law_nm)s, %(source)s
    )
    ON CONFLICT (bill_no) DO UPDATE SET
        plenary_dt       = EXCLUDED.plenary_dt,
        govt_transfer_dt = EXCLUDED.govt_transfer_dt,
        promulgation_dt  = EXCLUDED.promulgation_dt,
        prom_no          = EXCLUDED.prom_no,
        prom_law_nm      = EXCLUDED.prom_law_nm,
        source           = EXCLUDED.source,
        fetched_at       = now()
"""

_UPDATE_MISSING_PROPOSE_DT_SQL = """
    UPDATE bills
    SET propose_dt = %(propose_dt)s,
        fetched_at = now()
    WHERE bill_no = %(bill_no)s
      AND propose_dt IS NULL
"""


def backfill_bill_final_outcomes(
    *,
    limit: int | None = None,
    bill_nos: Sequence[str] | None = None,
    fetch_allbill: FetchAllbill = fetch_endpoint,
) -> BillFinalOutcomesBackfillResult:
    """ALLBILL을 BILL_NO별로 조회해 final outcomes와 결측 propose_dt를 채운다."""
    targets = _load_targets(bill_nos=bill_nos)
    eligible_targets = [
        target
        for target in targets
        if not (target.has_outcome and target.propose_dt is not None)
    ]
    fetch_targets = eligible_targets
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        fetch_targets = eligible_targets[:limit]

    fetched, failures = _fetch_allbill_rows(fetch_targets, fetch_allbill=fetch_allbill)
    outcome_rows = [
        _normalize_outcome_row(item.row)
        for item in fetched
        if item.target.is_passed
    ]
    propose_rows = [
        {"bill_no": item.target.bill_no, "propose_dt": _blank_to_none(item.row.get("PPSL_DT"))}
        for item in fetched
        if item.target.propose_dt is None and _blank_to_none(item.row.get("PPSL_DT")) is not None
    ]

    with get_conn() as conn:
        outcome_upserted_count = execute_many(conn, _UPSERT_OUTCOME_SQL, outcome_rows)
        propose_dt_updated_count = execute_many(
            conn,
            _UPDATE_MISSING_PROPOSE_DT_SQL,
            propose_rows,
        )
        conn.commit()

    no_data_count = sum(1 for failure in failures if failure.reason == "no_data")
    error_count = len(failures) - no_data_count
    accepted_gap_count = sum(
        1
        for row in outcome_rows
        if row["promulgation_dt"] is None
    )

    return BillFinalOutcomesBackfillResult(
        target_count=len(targets),
        skipped_count=len(targets) - len(eligible_targets),
        fetch_target_count=len(fetch_targets),
        fetched_count=len(fetched),
        outcome_target_count=sum(1 for item in fetched if item.target.is_passed),
        outcome_upserted_count=outcome_upserted_count,
        propose_dt_updated_count=propose_dt_updated_count,
        accepted_gap_count=accepted_gap_count,
        no_data_count=no_data_count,
        error_count=error_count,
        failures=tuple(failures),
    )


def _load_targets(*, bill_nos: Sequence[str] | None = None) -> list[BillFinalOutcomeTarget]:
    selected_bill_nos = _selected_bill_nos(bill_nos)
    if bill_nos is not None and not selected_bill_nos:
        return []

    filter_sql = ""
    params: list[object] = [sorted(PASSED_PROC_RESULTS)]
    if selected_bill_nos is not None:
        filter_sql = "AND b.bill_no = ANY(%s)"
        params.append(selected_bill_nos)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                b.bill_id,
                b.bill_no,
                b.propose_dt,
                b.proc_result,
                o.bill_no IS NOT NULL AS has_outcome
            FROM bills b
            LEFT JOIN bill_final_outcomes o ON o.bill_no = b.bill_no
            WHERE b.bill_no IS NOT NULL
              AND (
                  b.proc_result = ANY(%s)
                  OR b.propose_dt IS NULL
              )
              {filter_sql}
            ORDER BY b.propose_dt ASC NULLS FIRST, b.bill_no
            """,
            params,
        )
        return [
            BillFinalOutcomeTarget(
                bill_id=str(row[0]),
                bill_no=str(row[1]),
                propose_dt=row[2],
                proc_result=row[3],
                has_outcome=bool(row[4]),
            )
            for row in cur.fetchall()
        ]


def _selected_bill_nos(bill_nos: Sequence[str] | None) -> list[str] | None:
    if bill_nos is None:
        return None
    return sorted({str(bill_no) for bill_no in bill_nos if str(bill_no).strip()})


def _fetch_allbill_rows(
    targets: Sequence[BillFinalOutcomeTarget],
    *,
    fetch_allbill: FetchAllbill,
) -> tuple[list[_FetchedAllbillRow], list[BillFinalOutcomeFailure]]:
    fetched: list[_FetchedAllbillRow] = []
    failures: list[BillFinalOutcomeFailure] = []
    progress = ProgressReporter("ALLBILL final outcomes", len(targets))
    progress.start()
    for target in targets:
        response = fetch_allbill(ALLBILL_ENDPOINT, {"BILL_NO": target.bill_no})
        if response.status == "ok" and response.rows:
            fetched.append(_FetchedAllbillRow(target=target, row=dict(response.rows[0])))
            progress.advance()
            continue
        if response.status == "no_data":
            failures.append(
                BillFinalOutcomeFailure(
                    bill_id=target.bill_id,
                    bill_no=target.bill_no,
                    proc_result=target.proc_result,
                    reason="no_data",
                    error="ALLBILL returned no data",
                )
            )
            progress.advance(errors=1)
            continue
        if response.status == "ok" and not response.rows:
            failures.append(
                BillFinalOutcomeFailure(
                    bill_id=target.bill_id,
                    bill_no=target.bill_no,
                    proc_result=target.proc_result,
                    reason="no_data",
                    error="ALLBILL returned empty rows",
                )
            )
            progress.advance(errors=1)
            continue
        failures.append(
            BillFinalOutcomeFailure(
                bill_id=target.bill_id,
                bill_no=target.bill_no,
                proc_result=target.proc_result,
                reason="fetch_error",
                error=response.error or "ALLBILL fetch failed",
            )
        )
        progress.advance(errors=1)
    progress.finish()
    return fetched, failures


def _normalize_outcome_row(row: dict[str, Any]) -> dict[str, Any]:
    bill_no = _blank_to_none(row.get("BILL_NO"))
    if bill_no is None:
        raise ValueError("ALLBILL row missing BILL_NO")
    return {
        "bill_no": bill_no,
        "plenary_dt": _blank_to_none(row.get("RGS_RSLN_DT")),
        "govt_transfer_dt": _blank_to_none(row.get("GVRN_TRSF_DT")),
        "promulgation_dt": _blank_to_none(row.get("PROM_DT")),
        "prom_no": _blank_to_none(row.get("PROM_NO")),
        "prom_law_nm": _blank_to_none(row.get("PROM_LAW_NM")),
        "source": OUTCOME_SOURCE,
    }


def _blank_to_none(value: Any) -> Any | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value
