# API Catalog

PRD 확정 10개 OpenAPI의 작동 검증 결과. 1회성 — 자동 재검증 없음.
범위 결정 배경은 [ADR 0001](adr/0001-api-catalog-scope.md) 참고.

_Generated: 2026-05-26T14:33:18+00:00_

| endpoint | 이름 | 22대 데이터 | 22대 row 수 | status | usage |
|---|---|---|---|---|---|
| `BPMBILLSUMMARY` | 법률안 제안이유 및 주요내용 | ✓ | 1 | ok | bills.summary 채움 (BILL_NO 단위, 대수 무관) |
| `VCONFAPIGCONFLIST` | 국정감사 회의록 | ✓ | 317 | ok | meetings 적재 (ERACO=제22대) |
| `VCONFBILLCONFLIST` | 의안별 회의록 목록 | ✓ | 3 | ok | meeting_bills junction 적재 (BILL_ID 단위) |
| `VCONFCFRMCONFLIST` | 인사청문회 회의록 | ✓ | 64 | ok | meetings 적재 (ERACO=제22대) |
| `VCONFPIPCONFLIST` | 국정조사 회의록 | ✓ | 29 | ok | meetings 적재 (ERACO=제22대) |
| `ncwgseseafwbuheph` | 위원회 회의록 | ✓ | 12,822 | ok | meetings 적재 (DAE_NUM=22, CONF_DATE 연도별) |
| `nojepdqqaweusdfbi` | 국회의원 본회의 표결정보 | ✓ | 285 | ok | votes 적재 (BILL_ID 단위, 대수 무관) |
| `nwvrqwxyaytdsfvhu` | 국회의원 인적사항 | ✓ | 286 | ok | members 테이블 적재 (대수 무관, 22대 286명 대상) |
| `nzbyfwhwaoanttzje` | 본회의 회의록 | ✓ | 661 | ok | meetings 적재 (DAE_NUM=22, CONF_DATE 연도별) |
| `nzmimeepazxkubdpn` | 국회의원 발의법률안 | ✓ | 17,286 | ok | bills 테이블 적재 (AGE=22) |
