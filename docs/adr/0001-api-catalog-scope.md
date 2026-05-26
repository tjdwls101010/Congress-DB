# 0001. `api_catalog`은 PRD 확정 14개 API에 한정한다

## Context

원 PRD는 국회 OpenAPI 277개 전수를 1회성 검증해서 `api_catalog`에 적재하는
사용자 스토리(33)를 갖고 있었다. Slice 2 착수 직전 PM이 ROI를 재검토:
PRD는 이미 "외부 API 사용 목록 (확정)" 표로 14개 endpoint를 못박았고,
나머지 263개 API의 메타는 `.Seongjin/legacy_congress/국회 api.db`(SQLite)에
이미 보존되어 있다.

## Decision

`api_catalog` 테이블은 **PRD의 14개 사용 확정 API**만 적재한다.
검증·문서화·`used_in_pipeline=TRUE` 마킹은 모두 이 14건에 대해서만 수행한다.

263개 미사용 API의 메타는 legacy SQLite에 그대로 보존하고, 향후 새 API가
필요해지는 시점에 수동으로 조회·시험한다. 그때 `api_catalog`에 row를 추가하면 된다.

## Why

- **ROI**: 277회 호출 + retry + sleep ≈ 5–10분의 운영 비용을 들여 만든 263행을
  실무에서 거의 안 본다. 14건 검증은 30초.
- **목적 명확화**: 카탈로그가 "쓰는 API의 작동 검증"이라는 명확한 운영 가치를 갖는다.
- **거꾸로의 비용은 작음**: 미래에 카탈로그를 확장하고 싶어지면 같은
  `congress_db.api_client` wrapper로 호출 + INSERT 한 줄이면 끝.

## Out of scope (이번 결정으로 명시적으로 제외됨)

- 263개 미사용 API의 자동 검증
- 매일/주기 일괄 검증 스크립트 (이미 PRD에서 제외됐던 항목, 재확인)
- "혹시 좋은 API가 있을까" 발견 — 필요해지면 별도 manual 세션으로 분리
