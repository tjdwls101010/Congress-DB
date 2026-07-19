# Congress-DB

대한민국 국회 22대 임기(2024-05-30~) 데이터를 한 곳에 통합 적재하는 Postgres DB. 의원 한 명을 키로 그 의원의 발의 법안과 본회의 표결이 SQL JOIN 한 줄로 나오게 만드는 것이 목적이다.

> **회의·발언 도메인 제거 (2026-06-28, `migrations/031_drop_meeting_minutes.sql`):** `meetings`·`meeting_bills`·`utterances` 테이블, `bill_meeting_contexts` 뷰, `search_utterances` 함수가 삭제됐다. "누가 무엇을 말했나" 심층 분석은 websearch로 옮겼고(아래 **이 DB가 담지 않는 것** 참조), 심의 *진행·상태*는 구조화 테이블(`bills.proc_result`·`bill_lineage`·`bill_final_outcomes`)이 답한다. 배경은 [DECISIONS.md](docs/design/DECISIONS.md) 2026-06-28 참조.

스킬, AI agent, 개발자가 hosted Postgres에 read-only로 붙어 직접 SQL을 작성하는 것을 1차 소비 방식으로 둔다.

## 프로젝트 경계 / 로드맵

이 저장소는 4단계 로드맵의 **1단계(국회 데이터 DB)** 만 담는다. 각 단계는 독립 프로젝트이며, 경계를 넘는 기능은 다음 단계로 미뤄 스코프를 묶는다.

1. **국회 데이터 DB** — *이 저장소.* 22대 국회의 발의 법안·본회의 표결을 정규화 적재.
2. **국회 DB 직접 조회** — 별도 SDK를 만들지 않는다(DECISIONS 2026-06-10). 스킬이 이 DB의 자기설명(`schema.sql`·`ERD.md`=구조, 컬럼·테이블 `COMMENT`=함정·어휘)을 introspect하고, introspection이 조립 못 하는 cross-table 레시피만 `docs/design/DB-QUERY-GUIDE.md`에서 보며 read-only SQL로 직접 조회한다. 고정 SDK 표면의 브리틀니스(1개만 틀려도 막힘)를 피하고 클로드의 SQL 능력을 활용한다.
3. **법제처 데이터 접근 계층** — 현행법령·시행령·행정규칙·법령해석례(유권해석)·판례·헌재결정례를 법제처 OpenAPI에서 제공(별도 저장소). 국회는 API가 흩어져 DB 정규화가 필요했지만, 법제처는 `법령ID` 기반으로 본문·신구대조·체계도가 정연해 live API 또는 얇은 도구로 충분할 수 있다(3단계 진입 시 재판단).
4. **입법 harness (스킬)** — 국회 DB(직접 SQL)·법제처 데이터와 WebSearch(사회문제 맥락)를 함께 쓰는 입법 코파일럿(별도 저장소). 입법전문가가 사회문제를 놓고 현황·갭·사법해석·입법이력을 종합해 법안을 고안하도록 돕는다. `legislative-copilot` 프로토타입은 참고만, 새로 구축.

**이 DB가 담지 않는 것 (경계):**
- 시행 중인 **현행법·시행령 본문, 유권해석, 판례** → 3단계(법제처 데이터 접근 계층). 이 DB의 `bills`는 *발의된 의안*만이며 *시행 중인 법*과 구분한다(아래 **법안** 정의 참조).
- **회의록·발언(누가 무엇을 말했나)** → 범위 밖(2026-06-28 제거, 031). 심의 *진행·상태*는 구조화 테이블(`bills.proc_result`·`bill_lineage`·`bill_final_outcomes`)로 답하고, 발언 내용 심층 분석은 websearch로 넘긴다.
- **검색/조회 API, 의미 검색, 정책 의제 레이어** → 2단계 이후.
- **사회문제 맥락 수집(WebSearch)** → 4단계 harness.

## Language

**의원 (Member)**:
국회의원. 자연키는 `MONA_CD` (대수 구분 없는 의원 고유 코드). 이름이 같은 동명이인이 있을 수 있어 ID로 식별한다.
_Avoid_: 위원(위원회 컨텍스트에서의 호칭만으로 사용), 국회의원(전체 명칭으로 한 번 정도만)

**현직 여부 (Incumbency)**:
의원이 *현재 재직 중*인지를 나타내는 `members.is_incumbent`(BOOLEAN NOT NULL, 적재 완료 — 현재 현직 300·이탈 20). 손으로 관리하지 않고, 매 동기화 때 의원 인적사항 API(현직 명부)에 잡히면 TRUE, 안 잡히면 FALSE로 자동 갱신한다. 사퇴·의원직 상실 등으로 떠난 의원도 행은 그대로 두고(`ON DELETE RESTRICT`) `is_incumbent=FALSE`로만 표시해 행적 추적이 끊기지 않게 한다. 시점 정당(`poly_nm_at_vote`)과 같은 "출처에서 파생" 원칙을 따른다(별도 상태 테이블 없음). 사퇴 등으로 명부 동기화 전에 떠난 의원은 프로필 정당(`poly_nm`)이 NULL일 수 있다 — 시점 정당이 필요하면 `votes.poly_nm_at_vote`를 쓰고, 이를 `members.poly_nm`로 덮지 않는다(DECISIONS 2026-06-10).
_Avoid_: 활성/active(DB 활성 행과 혼동), 삭제

**법안 (Bill)**:
국회에 발의된 법률안 또는 의안. 자연키는 `BILL_ID` (`PRC_xxxx` 형식). 보조키는 `BILL_NO` (사람이 읽기 좋은 7자리 숫자, 예: 2218872).
_Avoid_: 법률, 법(이미 통과된 법은 별개 개념), 의안(법안 외에 임명동의안·추천안 등을 포함하므로 더 넓음 — 안건과 구분)

**대표발의자 (Lead Proposer)**:
한 법안의 대표로 이름이 올라가는 의원. 국회 API는 복수 대표발의자를 줄 수 있어 `bill_lead_proposers`에 정규화한다. `bill_lead_proposers`가 정본이며, 기존 `bills.rst_mona_cd` 단일 대표발의 편의 FK는 2026-06-13 cleanup에서 제거했다.
_Avoid_: 발의자(대표/공동 구분 안 됨)

**공동발의자 (Co-proposer)**:
대표발의 외에 이름을 함께 올린 의원들. N:M 관계. `bill_coproposers` 테이블에 정규화.

**원천 제안자 문구 (Raw Proposer Wording)**:
국회 법안 목록 원천의 `PROPOSER` 텍스트. 대표/공동발의자 identity는 `bill_lead_proposers`와 `bill_coproposers`가 정본이고, 이 문구는 `외 N인` 같은 서명자 수 힌트와 원천 표현을 보존하는 raw field다. 현재 컬럼명은 `bills.proposer_raw`이며, `bills.proposer`는 #121에서 제거된 과거 이름이다.
_Avoid_: proposer identity, member join key

**표결 (Vote)**:
**본회의 표결만** 다룬다. 위원회 단계의 가결·부결은 API가 제공하지 않아 추적하지 않는다. 본회의 표결 1건 = 그 표결에 기록된 의원 수만큼의 row(실측 285~300, 평균 ~297; 출결·의석 변동으로 가변 — 고정 286이 아니다).
_Avoid_: 의결, 통과, 가결(처리결과의 한 값일 뿐)

**정책 의제 (Policy Topic)**:
사용자가 검색하려는 정책 주제. 예: 전세사기, 의대정원, 채상병 특검, AI 기본법. 향후 `policy_topics` 같은 의미 레이어에서 다룬다.
_Avoid_: 안건(국회 공식 상정 항목과 혼동)

**위원회 (Committee)**:
상임위원회 / 특별위원회 / 소위원회. 의원은 시점마다 소속 위원회가 다를 수 있지만, **별도 history 테이블은 두지 않는다** — 법안 소관 위원회는 `bills.committee_id → committees`로만 본다(위원회 시점별 membership/history는 범위 밖).

**대수 (Assembly Term)**:
"제22대"처럼 4년 임기 단위. 본 DB는 22대(2024-05-30~)만 다룬다. API 파라미터로 `DAE_NUM=22` / `AGE=22` / `ERACO=제22대` 형식이 혼재한다.

**MONA_CD**:
국회의원 고유 코드 (예: `T2T8225E`). 대수에 무관한 의원 식별자. 우리 DB의 `members.mona_cd` PK.

**BILL_ID / BILL_NO**:
- `BILL_ID`: `PRC_D2C6E...` 형식. `bills` PK이자 한 source 안의 식별자. **단, source마다 같은 의안에 다른 BILL_ID를 줄 수 있다** — likms/ALLBILL의 BILL_ID와 우리 `bills`의 BILL_ID가 갈리는 사례 확인(DECISIONS 2026-06-10). BILL_ID를 cross-source 영구키로 가정하지 말 것.
- `BILL_NO`: `2218872` 같은 7자리 숫자. **source 간 안정적인 키.** likms·ALLBILL이 BILL_NO로 조회된다. 의안 동일성 판단·alias 해소의 기준은 BILL_NO다.
- `bill_source_aliases`: source별 BILL_ID를 canonical `bills` row(BILL_NO 기준)에 잇는 정규화. **적재 완료**이나 ETL-internal이라 `congress_ro`에서 REVOKE된다(소비자는 `bill_lineage` 뷰로 계보를 읽음, #125).

**처리결과 (Proc Result)**:
법안의 본회의 처리결과. 가결·부결·대안반영·철회 등. `bills.proc_result`에 텍스트로 저장.

**최종 처리·공포 이력 (Final Outcome)**:
법안의 본회의 의결 이후 정부이송·공포 단계. 공포일·공포번호·정부이송일·공포 법률명(`prom_law_nm`)을 ALLBILL에서 `BILL_NO` 기준으로 적재해 `bill_final_outcomes`에 보존한다(DECISIONS 2026-06-10, 2026-06-11). `bills.law_proc_dt`(법사위 처리일에 가까움)와 **다르다** — law_proc_dt를 공포일로 쓰지 말 것. 현행법 본문은 법제처 단계 소관이고, 이 이력은 법제처 질의로 이어지는 bridge key다.
_Avoid_: law_proc_dt를 공포일로 사용

**의안유형 (Proposal Type / `bill_kind`)** _(도입 예정 — M3)_:
`bills`에 섞인 의안의 종류. 법률안(공포 대상) vs 비-법률 의안(감사요구안·수사요구안·규칙안·결의안·동의안·승인안 — 공포 비대상). 원천에 종류 필드가 없어 `bill_name`에서 파생하며(특별법안·특별조치법안도 법률안), "통과했는데 공포 없음"이 정상(비대상)인지 결측인지를 가른다.
_Avoid_: 법안종류(법안=법률안에 한정되어 좁음)

**법안 문서 (Bill Document)** _(prototype-gated — 미적재)_:
법안 원문·비용추계의 파일 URL(`BILLRCPV2`가 `BILL_ID` 키로 `BOOK_*`=원문·`COST_*`=비용추계 HWP/PDF 제공). **현재 DB에 적재하지 않음** — 2026-06-12 `bill_documents`로 적재했다 demand 미입증으로 되돌림(DECISIONS 2026-06-12). 스킬 프로토타입이 문서 링크 수요를 입증하면 재구축(방법은 이슈 #96에 보존).

**청원 / 공청회 / 입법예고 (Petition / Public Hearing / Legislative Notice)** _(도입 예정 — M3)_:
국회의 공식 시민수요·전문가증언·의견수렴 source. 청원(`PTT_ID`, 302건)은 시민 요구의 공식 신호이되 '여론' 대표성으로 단정하지 않는다(해석은 [4]). 공청회(59건)는 별도 inventory·파싱검증 대상. 입법예고(17,708건)는 notice 메타만, 의견 본문은 범위 밖.

**위원회 차원 (Committee Dimension)**:
`bills.committee_id -> committee_name`을 canonical하게 보존하는 bill-side 소관 위원회/기관 dimension. 2026-06-13 Neon main 감사에서 31개 id/name pair가 1:1(충돌 0)로 확인되어, #120에서 `committees`를 만들고 `bills.committee_id` FK를 건 뒤 중복 display field `bills.committee`를 제거했다. 위원회 **membership**(누가 어느 위원)은 명부 API 검증 후에만 — 별개 개념이다.
_Avoid_: 위원회 history(시점별 membership — 검증 전까지 제외)

**대안 관계 (Alternative Relation)**:
위원회 심사에서 여러 법안 내용을 통합해 새 **대안**(또는 **수정안**)을 만들고 원안들을 *대안반영폐기*(또는 *수정안반영폐기*)할 때, 폐기된 원안과 그 내용을 흡수한 대안/수정안 법안 사이의 연결. 국회 OpenAPI엔 이 관계 필드가 없어, 의안정보시스템(likms) 상세페이지의 `selRefBillId` 숨은 필드를 스크래핑해 채운다(DECISIONS 2026-06-06). 이 연결이 없으면 "이 주제가 과거에 어떻게 입법됐고 무엇이 법으로 남았나"를 추적할 수 없다(대안반영폐기 3,676 + 수정안반영폐기 39건). _(소비 표면 — #125, DECISIONS 2026-06-14)_: raw `bill_relations`/`bill_source_aliases`는 ETL-internal(ops)로 내려 `congress_ro`에서 REVOKE했고, 소비자는 direct+alias 해소를 캡슐화한 **`bill_lineage` 뷰**로 폐기원안→해소된 canonical 대안을 읽는다(미해소는 `alternative_bill_id=NULL`로 노출, `relation_type`은 `proc_result`에서 파생; raw `relation_type` 물리 컬럼은 ETL 사용으로 KEEP).
_Avoid_: 병합(코드 merge와 혼동)

**백필 (Backfill)**:
22대 시작일(2024-05-30)부터 현재까지 누적 데이터를 한 번에 채우는 초기 전체 적재 실행. 이후 증분 수집과 같은 적재 Module을 사용하고, 실행 범위만 전체로 잡는다.
_Avoid_: 일회성 스크립트, 초기 전용 코드

**증분 동기화 (Incremental Sync)**:
백필 이후 새로 생기거나 뒤늦게 변경된 데이터를 주기적으로 다시 가져와 upsert하는 실행. 싼 목록 endpoint는 매 실행 전체를 다시 훑어 오래된 기록의 뒤늦은 변경(처리결과·정정)까지 잡고, 한 번 확정되면 안 바뀌는 항목(법안 summary·표결 상세)은 이미 있는 것을 다시 받지 않는다. (이전의 'source별 cursor + 30일 overlap window' 설계는 뒤늦은 변경을 놓쳐 폐기 — DECISIONS 2026-06-04 / 이슈 #46.)
_Avoid_: 신규 row만 추가(변경 데이터가 누락됨)

**수집 명령 (Ingest Command)**:
PM과 운영자가 실행하는 단일 공개 명령. 내부적으로 백필/증분/재시도/검증을 조율하되, 사용자는 개별 source 적재 순서나 재실행 조건을 직접 조합하지 않는다.
_Avoid_: stage별 수동 실행, 임시 백필 스크립트

**수집 실행 (Ingest Run)**:
백필, 증분 동기화, dead letter 재처리 중 하나를 실행한 기록. 상태는 `running`, `success`, `degraded_success`, `failed`, `blocked` 중 하나다.

**수집 커서 (Ingest Cursor)**:
각 source가 마지막으로 성공 처리한 기준점. 법안·표결은 날짜 의미가 달라 하나의 global cursor를 쓰지 않고 source별로 분리한다. (개정 2026-06-04: cursor는 fetch 범위를 좁히는 데 쓰지 않고 마지막 성공 시점 관찰용으로만 남긴다 — DECISIONS 2026-06-04 / 이슈 #46.)
_Avoid_: global cursor

**실패 편지 (Dead Letter)**:
재시도 후에도 실패한 API item. 삭제하지 않고 `pending`/`resolved` 등 상태로 보존해 누락과 지연 적재 원인을 추적한다.
_Avoid_: 터미널 로그만 남기기, 실패 item 무시

## Relationships

- **의원 ↔ 법안 (대표발의)**: 한 법안에 한 명 이상 **대표발의자**가 있을 수 있다. bill_lead_proposers 정규화 테이블.
- **의원 ↔ 법안 (공동발의)**: N:M. bill_coproposers 정규화 테이블.
- **의원 ↔ 법안 (표결)**: N:M. votes 테이블 (의안 1개당 ~285~300 row, 평균 ~297; 고정 286 아님).
- **수집 실행 → 실패 편지**: 1:N. dead_letters.run_id FK.
- **수집 커서 → 수집 실행**: source별 cursor가 마지막 성공 run을 가리킨다.

## Example dialogue

> **PM**: 위원회 단계의 표결 결과도 필요한가?
> **개발자**: API가 본회의 표결만 제공한다. 위원회 표결 추출은 정밀도가 낮다. 본회의 표결만 다루자.

> **PM**: 2년치 초기 적재와 이후 신규 데이터 추가 코드를 따로 만들까?
> **개발자**: 따로 만들면 drift가 생긴다. 같은 적재 Module을 사용하고, 백필은 전체 범위, 증분 동기화는 source별 cursor + 30일 overlap으로 실행 범위만 다르게 잡자.
>
> *(주: 'cursor + 30일 overlap' 메커니즘은 2026-06-04 폐기 — 증분은 싼 목록 전체 재스캔 + 불변 항목 skip. '같은 Module, mode만 다름' 원칙은 유지. DECISIONS 2026-06-04 / 이슈 #46.)*

## Flagged ambiguities

- **"정책 의제" vs "법안"**: 정책 의제는 사용자가 찾는 주제, 법안은 `BILL_ID`로 식별되는 의안이다. core DB에는 법안만 보존하고, 정책 의제는 향후 의미 레이어에서 다룬다.
- **"의원" vs "위원"**: 같은 사람이지만 위원회 컨텍스트에서는 "위원"으로 호칭됨. 식별·join은 `mona_cd`로 한다.
- **의원 인적사항 API의 범위**: `nwvrqwxyaytdsfvhu`는 *현직* 의원만 반환하며(관측 시점 286명; 사퇴·재보궐 등으로 변동) 법안·표결 API는 그 밖의 22대 관련 MONA_CD도 참조한다. FK와 JOIN을 보존하기 위해 적재 중 발견한 누락 의원은 최소 이름만 가진 `members` stub으로 보존한다. **현직 여부**(`is_incumbent`)는 이 명부 등장 여부로 판정한다 — 명부에 없는 stub·퇴직자는 FALSE이며, 행은 삭제하지 않는다.
- **대수 파라미터 형식 혼재**: `DAE_NUM=22` (정수) vs `AGE=22` (정수) vs `ERACO=제22대` (한글 텍스트). API별로 다르므로 한 군데 wrapper에서 흡수.
- **백필 vs 증분 동기화**: 별도 코드가 아니라 같은 적재 Module의 실행 mode다. 초기에는 로컬/별도 runner가 hosted Postgres DB에 직접 upsert한다.
- **검색 recall은 DB가 아니라 스킬 inform 영역** (DECISIONS 2026-06-14): `search_bills`는 ILIKE 부분문자열 매칭이라 질의 문자열이 `bill_name`/`summary`에 그대로 박혀야 잡힌다. tsvector FTS는 한국어 형태소 분석기 부재로 recall이 ILIKE에 strictly dominated(옮기지 말 것). recall 손실의 주범은 본문에 그대로 없는 별칭(예: 김영란법→0건; 단 노란봉투법은 한 법안 summary에 적혀 1건 잡힘 — 즉 통칭이라도 본문에 적혀 있으면 잡힌다)·동의어(저출생↔저출산) 갭이며, 이는 스킬이 통칭→정식명 치환 + 질의확장으로 보완한다(별칭사전은 스킬 PRD 소관). 광역 토픽은 `result_limit`을 크게(200+) 주어 50-cap 절단을 피한다.
