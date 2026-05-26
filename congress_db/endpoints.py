"""PRD 확정 사용 OpenAPI 11개 정의.

이 모듈은 single source of truth로, `api_catalog` 적재·검증·향후 적재 스크립트
모두 이 상수를 import해서 사용한다. 새 endpoint를 쓰기 시작하면 여기 추가
하고 ADR 또는 PRD 업데이트.

회의록 본문 HTML(`record.assembly.go.kr/.../xml.do`)은 OpenAPI가 아니라
스크래핑이라 별도 — 여기 포함하지 않는다.

## 적재 시 알아두어야 할 운영 디테일

이번 카탈로그 검증(Slice 2)에서 발견한 사실들. 적재 슬라이스(#4 이후)에서
다시 디버그하지 않도록 spec 옆 코멘트로 박아둔다.

- **`CONF_DATE`는 YYYY (연도) 형식**. YYYYMMDD가 아님. 연-월(YYYY-MM)도 허용.
  본회의/위원회 회의록은 `DAE_NUM=22 + CONF_DATE` 둘 다 필수.
- **본회의 표결(`nojepdqqaweusdfbi`)과 의안별 회의록(`VCONFBILLCONFLIST`)은
  본회의 통과 법안의 BILL_ID에만 row 존재**. 발의만 된 법안은 no_data.
- **`BPMBILLSUMMARY`는 BILL_NO 단위 1:1 호출**. legacy SQLite에 endpoint 컬럼이
  비어 있는 데이터 결함이 있어 endpoint slug는 코드에서 직접 박음.
- **국정감사/국정조사/인사청문회는 ERACO='제22대'** (다른 endpoint와 형식 다름).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EndpointSpec:
    """PRD 확정 사용 OpenAPI 1개의 메타.

    Attributes:
        inf_id: 국회 OpenAPI 시스템 내부 ID (api_catalog PK).
        endpoint: 호출 URL slug.
        name: 한국어 이름.
        usage_note: 어디에 쓰이는지 + 핵심 대수 파라미터 힌트.
        verify_sample: 1회성 검증 호출 시 박을 sample 파라미터.
            적재 시에는 호출자가 진짜 값(실제 BILL_ID, CONF_DATE 등)을 채움.
            대수 파라미터는 wrapper의 `fetch_with_age_attempts`가 자동 시도하므로
            여기에 안 박는다 (`DAE_NUM`/`AGE`/`ERACO`).
    """

    inf_id: str
    endpoint: str
    name: str
    usage_note: str
    verify_sample: dict[str, str] | None = None


# PRD docs/PRD.md의 "외부 API 사용 목록 (확정)" 표 그대로.
# inf_id는 `.Seongjin/legacy_congress/국회 api.db`(SQLite)에서 확인.
PIPELINE_ENDPOINTS: tuple[EndpointSpec, ...] = (
    EndpointSpec(
        inf_id="OWSSC6001134T516707",
        endpoint="nwvrqwxyaytdsfvhu",
        name="국회의원 인적사항",
        usage_note="members 테이블 적재 (대수 무관, 22대 286명 대상)",
        # 대수 무관 — wrapper가 자동으로 시도하지만 결국 어떤 대수 파라미터도 안 박혀도 OK.
        verify_sample=None,
    ),
    EndpointSpec(
        inf_id="OK7XM1000938DS17215",
        endpoint="nzmimeepazxkubdpn",
        name="국회의원 발의법률안",
        usage_note="bills 테이블 적재 (AGE=22, pagination 필수, 22대 17,286건)",
        # 대수 파라미터만 박으면 됨. pagination(pIndex/pSize)로 17k건 순회.
        verify_sample=None,
    ),
    EndpointSpec(
        # BPMBILLSUMMARY는 legacy SQLite에 inf_id만 있고 endpoint 컬럼이 비어 있음
        # (legacy 데이터 결함). endpoint는 우리가 직접 박는다.
        inf_id="OS46YD0012559515463",
        endpoint="BPMBILLSUMMARY",
        name="법률안 제안이유 및 주요내용",
        usage_note="bills.summary 채움 (BILL_NO 단위 1:1, 대수 무관)",
        # 적재 시: 모든 bills.bill_no에 대해 1회씩 호출.
        # 검증 시: 22대 첫 법안 BILL_NO 하나 박아 작동 확인.
        verify_sample={"BILL_NO": "2219057"},
    ),
    EndpointSpec(
        inf_id="OO1X9P001017YF13038",
        endpoint="nzbyfwhwaoanttzje",
        name="본회의 회의록",
        # ⚠️ CONF_DATE는 YYYY 형식. YYYYMMDD 아님 — legacy fetch_meetings.py::_date_range 확인.
        usage_note="meetings 적재 — DAE_NUM=22 + CONF_DATE(YYYY 또는 YYYY-MM) 둘 다 필수",
        verify_sample={"CONF_DATE": "2024"},
    ),
    EndpointSpec(
        inf_id="OR137O001023MZ19321",
        endpoint="ncwgseseafwbuheph",
        name="위원회 회의록",
        # ⚠️ 본회의 회의록과 동일한 패턴.
        usage_note="meetings 적재 — DAE_NUM=22 + CONF_DATE(YYYY 또는 YYYY-MM) 둘 다 필수",
        verify_sample={"CONF_DATE": "2024"},
    ),
    EndpointSpec(
        inf_id="OOWY4R001216HX11507",
        endpoint="VCONFAPIGCONFLIST",
        name="국정감사 회의록",
        usage_note="meetings 적재 (ERACO=제22대, 22대 317건)",
        verify_sample=None,
    ),
    EndpointSpec(
        inf_id="OOWY4R001216HX11508",
        endpoint="VCONFPIPCONFLIST",
        name="국정조사 회의록",
        usage_note="meetings 적재 (ERACO=제22대, 22대 29건)",
        verify_sample=None,
    ),
    EndpointSpec(
        inf_id="OOWY4R001216HX11509",
        endpoint="VCONFCFRMCONFLIST",
        name="인사청문회 회의록",
        usage_note="meetings 적재 (ERACO=제22대, 22대 64건)",
        verify_sample=None,
    ),
    EndpointSpec(
        inf_id="OND1KZ0009677M13515",
        endpoint="ncocpgfiaoituanbr",
        name="의안별 표결현황",
        usage_note="votes 적재 후보 BILL_ID 목록 (AGE=22, 22대 표결 의안 1,595건)",
        verify_sample=None,
    ),
    EndpointSpec(
        inf_id="OPR1MQ000998LC12535",
        endpoint="nojepdqqaweusdfbi",
        name="국회의원 본회의 표결정보",
        # ⚠️ 발의만 된 법안은 row 없음. 본회의 통과 법안(proc_result='원안가결' 등)만.
        usage_note="votes 적재 (AGE=22 + BILL_ID 단위, 본회의 통과 법안만 row 존재)",
        verify_sample={"BILL_ID": "PRC_O2C5J0H9H1H0P1O0M1N9M3G4G6M5N6"},
    ),
    EndpointSpec(
        inf_id="OOWY4R001216HX11526",
        endpoint="VCONFBILLCONFLIST",
        name="의안별 회의록 목록",
        # ⚠️ 본회의 표결과 동일 — 본회의 통과 법안만 row 존재.
        usage_note="meeting_bills junction 적재 (BILL_ID 단위, 본회의 통과 법안만)",
        verify_sample={"BILL_ID": "PRC_O2C5J0H9H1H0P1O0M1N9M3G4G6M5N6"},
    ),
)


# 빠른 lookup용 dict.
ENDPOINTS_BY_SLUG: dict[str, EndpointSpec] = {
    spec.endpoint: spec for spec in PIPELINE_ENDPOINTS
}
