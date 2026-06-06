"""members 테이블 적재.

deep module: 호출자는 `ingest_members()` 한 함수만 알면 된다. 국회 OpenAPI 호출,
응답 검증, row 정규화, `ON CONFLICT` upsert는 내부에 숨긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.api_client import ApiResponse, fetch_with_age_attempts
from ..core.db import execute_many, get_conn
from ..core.endpoints import ENDPOINTS_BY_SLUG

MEMBERS_ENDPOINT = "nwvrqwxyaytdsfvhu"
MEMBERS_PAGE_SIZE = 300
MEMBERS_SPEC = ENDPOINTS_BY_SLUG[MEMBERS_ENDPOINT]


@dataclass(frozen=True)
class IngestMembersResult:
    """members 적재 결과."""

    total_count: int
    fetched_count: int
    upserted_count: int
    age_param_used: dict[str, str] | None


_MEMBER_FIELDS: tuple[str, ...] = (
    "mona_cd",
    "hg_nm",
    "hj_nm",
    "eng_nm",
    "bth_date",
    "sex_gbn_nm",
    "poly_nm",
    "orig_nm",
    "elect_gbn_nm",
    "cmits",
    "reele_gbn_nm",
    "units",
    "tel_no",
    "e_mail",
    "homepage",
    "mem_title",
    "assem_addr",
)

_API_TO_DB: dict[str, str] = {
    "MONA_CD": "mona_cd",
    "HG_NM": "hg_nm",
    "HJ_NM": "hj_nm",
    "ENG_NM": "eng_nm",
    "BTH_DATE": "bth_date",
    "SEX_GBN_NM": "sex_gbn_nm",
    "POLY_NM": "poly_nm",
    "ORIG_NM": "orig_nm",
    "ELECT_GBN_NM": "elect_gbn_nm",
    "CMITS": "cmits",
    "REELE_GBN_NM": "reele_gbn_nm",
    "UNITS": "units",
    "TEL_NO": "tel_no",
    "E_MAIL": "e_mail",
    "HOMEPAGE": "homepage",
    "MEM_TITLE": "mem_title",
    "ASSEM_ADDR": "assem_addr",
}

_UPSERT_MEMBERS_SQL = """
    INSERT INTO members (
        mona_cd, hg_nm, hj_nm, eng_nm, bth_date, sex_gbn_nm,
        poly_nm, orig_nm, elect_gbn_nm, cmits, reele_gbn_nm, units,
        tel_no, e_mail, homepage, mem_title, assem_addr, is_incumbent
    )
    VALUES (
        %(mona_cd)s, %(hg_nm)s, %(hj_nm)s, %(eng_nm)s, %(bth_date)s, %(sex_gbn_nm)s,
        %(poly_nm)s, %(orig_nm)s, %(elect_gbn_nm)s, %(cmits)s, %(reele_gbn_nm)s, %(units)s,
        %(tel_no)s, %(e_mail)s, %(homepage)s, %(mem_title)s, %(assem_addr)s, TRUE
    )
    ON CONFLICT (mona_cd) DO UPDATE SET
        hg_nm        = EXCLUDED.hg_nm,
        hj_nm        = EXCLUDED.hj_nm,
        eng_nm       = EXCLUDED.eng_nm,
        bth_date     = EXCLUDED.bth_date,
        sex_gbn_nm   = EXCLUDED.sex_gbn_nm,
        poly_nm      = EXCLUDED.poly_nm,
        orig_nm      = EXCLUDED.orig_nm,
        elect_gbn_nm = EXCLUDED.elect_gbn_nm,
        cmits        = EXCLUDED.cmits,
        reele_gbn_nm = EXCLUDED.reele_gbn_nm,
        units        = EXCLUDED.units,
        tel_no       = EXCLUDED.tel_no,
        e_mail       = EXCLUDED.e_mail,
        homepage     = EXCLUDED.homepage,
        mem_title    = EXCLUDED.mem_title,
        assem_addr   = EXCLUDED.assem_addr,
        is_incumbent = TRUE,
        fetched_at   = now()
"""


def ingest_members() -> IngestMembersResult:
    """국회 의원 인적사항 API에서 22대 의원을 받아 members에 upsert한다."""
    response = _fetch_members()
    rows = [_normalize_member_row(row) for row in response.rows]

    with get_conn() as conn:
        _mark_all_members_non_incumbent(conn)
        upserted = _upsert_members(conn, rows)
        conn.commit()

    return IngestMembersResult(
        total_count=response.total_count,
        fetched_count=len(rows),
        upserted_count=upserted,
        age_param_used=response.age_param_used,
    )


def _fetch_members() -> ApiResponse:
    response = fetch_with_age_attempts(
        MEMBERS_SPEC.endpoint,
        MEMBERS_SPEC.verify_sample,
        p_size=MEMBERS_PAGE_SIZE,
    )
    if response.status != "ok":
        detail = response.error or response.status
        raise RuntimeError(f"members API fetch failed: {detail}")
    if len(response.rows) != response.total_count:
        raise RuntimeError(
            "members API returned partial page: "
            f"rows={len(response.rows)} total_count={response.total_count}"
        )
    return response


def _normalize_member_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = {field: None for field in _MEMBER_FIELDS}
    for api_field, db_field in _API_TO_DB.items():
        normalized[db_field] = _blank_to_none(row.get(api_field))

    if not normalized["mona_cd"]:
        raise ValueError("members API row missing MONA_CD")
    if not normalized["hg_nm"]:
        raise ValueError(f"members API row missing HG_NM: {normalized['mona_cd']}")
    return normalized


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _upsert_members(conn: Any, rows: list[dict[str, Any]]) -> int:
    return execute_many(conn, _UPSERT_MEMBERS_SQL, rows)


def _mark_all_members_non_incumbent(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE members SET is_incumbent = FALSE WHERE is_incumbent")
