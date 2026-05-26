"""PRD 확정 사용 OpenAPI 10개 정의.

이 모듈은 단일 source of truth로, `api_catalog` 적재와 향후 적재 스크립트
모두 이 상수를 import해서 사용한다. 새 endpoint를 쓰기 시작하면 여기 추가
하고 ADR 또는 PRD 업데이트.

회의록 본문 HTML(`record.assembly.go.kr/.../xml.do`)은 OpenAPI가 아니라
스크래핑이라 별도 — 여기 포함하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EndpointSpec:
    """PRD 확정 사용 OpenAPI 1개의 메타."""

    inf_id: str          # 국회 OpenAPI 시스템 내부 ID (api_catalog PK)
    endpoint: str        # 호출 URL slug
    name: str            # 한국어 이름
    usage_note: str      # 어디에 쓰이는지 (api_catalog.usage_note)


# PRD docs/PRD.md의 "외부 API 사용 목록 (확정)" 표 그대로.
# inf_id는 `.Seongjin/legacy_congress/국회 api.db`(SQLite)에서 확인.
PIPELINE_ENDPOINTS: tuple[EndpointSpec, ...] = (
    EndpointSpec(
        inf_id="OWSSC6001134T516707",
        endpoint="nwvrqwxyaytdsfvhu",
        name="국회의원 인적사항",
        usage_note="members 테이블 적재 (대수 무관, 22대 286명 대상)",
    ),
    EndpointSpec(
        inf_id="OK7XM1000938DS17215",
        endpoint="nzmimeepazxkubdpn",
        name="국회의원 발의법률안",
        usage_note="bills 테이블 적재 (AGE=22)",
    ),
    EndpointSpec(
        # BPMBILLSUMMARY는 legacy SQLite에 inf_id만 있고 endpoint 컬럼이 비어 있음
        # (legacy 데이터 결함). endpoint는 우리가 직접 박는다.
        inf_id="OS46YD0012559515463",
        endpoint="BPMBILLSUMMARY",
        name="법률안 제안이유 및 주요내용",
        usage_note="bills.summary 채움 (BILL_NO 단위, 대수 무관)",
    ),
    EndpointSpec(
        inf_id="OO1X9P001017YF13038",
        endpoint="nzbyfwhwaoanttzje",
        name="본회의 회의록",
        usage_note="meetings 적재 (DAE_NUM=22, CONF_DATE 연도별)",
    ),
    EndpointSpec(
        inf_id="OR137O001023MZ19321",
        endpoint="ncwgseseafwbuheph",
        name="위원회 회의록",
        usage_note="meetings 적재 (DAE_NUM=22, CONF_DATE 연도별)",
    ),
    EndpointSpec(
        inf_id="OOWY4R001216HX11507",
        endpoint="VCONFAPIGCONFLIST",
        name="국정감사 회의록",
        usage_note="meetings 적재 (ERACO=제22대)",
    ),
    EndpointSpec(
        inf_id="OOWY4R001216HX11508",
        endpoint="VCONFPIPCONFLIST",
        name="국정조사 회의록",
        usage_note="meetings 적재 (ERACO=제22대)",
    ),
    EndpointSpec(
        inf_id="OOWY4R001216HX11509",
        endpoint="VCONFCFRMCONFLIST",
        name="인사청문회 회의록",
        usage_note="meetings 적재 (ERACO=제22대)",
    ),
    EndpointSpec(
        inf_id="OPR1MQ000998LC12535",
        endpoint="nojepdqqaweusdfbi",
        name="국회의원 본회의 표결정보",
        usage_note="votes 적재 (BILL_ID 단위, 대수 무관)",
    ),
    EndpointSpec(
        inf_id="OOWY4R001216HX11526",
        endpoint="VCONFBILLCONFLIST",
        name="의안별 회의록 목록",
        usage_note="meeting_bills junction 적재 (BILL_ID 단위)",
    ),
)


# 빠른 lookup용 dict.
ENDPOINTS_BY_SLUG: dict[str, EndpointSpec] = {
    spec.endpoint: spec for spec in PIPELINE_ENDPOINTS
}
