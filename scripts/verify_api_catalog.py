#!/usr/bin/env python3
"""api_catalog verify CLI — 10개 endpoint를 실제 호출해서 결과를 DB에 기록.

사용법::

    make db-up                                  # Postgres + 스키마
    uv run python scripts/seed_api_catalog.py   # 10행 seed
    uv run python scripts/verify_api_catalog.py # 실제 호출 + status 업데이트

각 호출은 `fetch_with_age_attempts`로 4가지 대수 파라미터를 자동 시도한다.
pSize=1로 호출 — 우리가 알고 싶은 건 "작동하는가 / row가 있는가"이지 데이터
자체를 받아오는 것이 아님. 결과는 api_catalog에 영구 기록.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from congress_db.api_catalog import update_verification_result
from congress_db.api_client import fetch_with_age_attempts
from congress_db.endpoints import PIPELINE_ENDPOINTS, EndpointSpec


# verify 시 endpoint별로 추가로 박아야 하는 파라미터.
# - CONF_DATE는 YYYY 형식(연도) — legacy fetch_meetings.py에서 확인.
# - BILL_NO/BILL_ID는 22대 첫 법안 샘플. "endpoint가 작동하는가" 검증이 목적이므로
#   sample이 어떤 값인지는 무관, 실제로 존재하는 값이기만 하면 됨.
_SAMPLE_PASSED_BILL_ID = "PRC_O2C5J0H9H1H0P1O0M1N9M3G4G6M5N6"  # 22대 본회의 통과 법안 (verify 시점)

VERIFY_EXTRAS: dict[str, dict[str, str]] = {
    "nzbyfwhwaoanttzje": {"CONF_DATE": "2024"},
    "ncwgseseafwbuheph": {"CONF_DATE": "2024"},
    "BPMBILLSUMMARY":    {"BILL_NO": "2219057"},
    # 표결·의안별 회의록은 본회의 통과까지 간 법안이어야 row 발생.
    "nojepdqqaweusdfbi": {"BILL_ID": _SAMPLE_PASSED_BILL_ID},
    "VCONFBILLCONFLIST": {"BILL_ID": _SAMPLE_PASSED_BILL_ID},
}


@dataclass
class VerifyOutcome:
    spec: EndpointSpec
    status: str
    total_count: int
    age_param: dict[str, str] | None
    skip_reason: str | None


def verify_one(spec: EndpointSpec) -> VerifyOutcome:
    """단일 endpoint를 호출하고 결과를 정규화."""
    extras = VERIFY_EXTRAS.get(spec.endpoint)
    response = fetch_with_age_attempts(
        spec.endpoint,
        extras,
        p_size=1,
        sleep_between=0.1,
    )
    skip_reason: str | None = None
    if response.status == "no_data":
        skip_reason = (
            "필수 파라미터(BILL_NO/BILL_ID 등) 부재 또는 22대 데이터 없음"
        )
    elif response.status == "error":
        skip_reason = f"호출 실패: {response.error or 'unknown'}"

    update_verification_result(
        spec.inf_id,
        status=response.status,
        has_22nd_data=(response.status == "ok"),
        total_count_22nd=response.total_count if response.status == "ok" else None,
        skip_reason=skip_reason,
    )
    return VerifyOutcome(
        spec=spec,
        status=response.status,
        total_count=response.total_count,
        age_param=response.age_param_used,
        skip_reason=skip_reason,
    )


def _format_row(idx: int, total: int, o: VerifyOutcome) -> str:
    age = (
        next(iter(o.age_param.keys())) + "=" + next(iter(o.age_param.values()))
        if o.age_param else "—"
    )
    return (
        f"[{idx:>2}/{total}] {o.spec.endpoint:<22} {o.status:<8} "
        f"count={o.total_count:>7} age={age}"
    )


def main() -> None:
    total = len(PIPELINE_ENDPOINTS)
    print(f"Verifying {total} endpoints…")
    for i, spec in enumerate(PIPELINE_ENDPOINTS, 1):
        outcome = verify_one(spec)
        print(_format_row(i, total, outcome))
    print("Done.")


if __name__ == "__main__":
    main()
