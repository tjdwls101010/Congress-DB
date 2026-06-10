# Congress-DB

대한민국 국회 22대 임기(2024-05-30~) 데이터를 한 곳에 통합 적재하는 Postgres DB. 의원 한 명을 키로 그 의원의 발의 법안, 본회의 표결, 회의록 발언이 SQL JOIN 한 줄로 나오게 만드는 것이 목적이다.

향후 검색 API/SDK를 그 위에 얹는다. 1차 적재 후 hosted Postgres로 마이그레이션한다.

## 프로젝트 경계 / 로드맵

이 저장소는 4단계 로드맵의 **1단계(국회 데이터 DB)** 만 담는다. 각 단계는 독립 프로젝트이며, 경계를 넘는 기능은 다음 단계로 미뤄 스코프를 묶는다.

1. **국회 데이터 DB** — *이 저장소.* 22대 국회의 발의 법안·본회의 표결·회의록 발언을 정규화 적재.
2. **국회 DB 직접 조회** — 별도 SDK를 만들지 않는다(DECISIONS 2026-06-10). 스킬이 이 DB의 스키마·활용 레퍼런스를 보고 read-only SQL로 직접 조회한다. 고정 SDK 표면의 브리틀니스(1개만 틀려도 막힘)를 피하고 클로드의 SQL 능력을 활용한다.
3. **법제처 SDK** — 현행법령·시행령·행정규칙·법령해석례(유권해석)·판례·헌재결정례를 법제처 OpenAPI에서 제공(별도 저장소). 국회는 API가 흩어져 DB 정규화가 필요했지만, 법제처는 `법령ID` 기반으로 본문·신구대조·체계도가 정연해 live API+SDK로 충분할 수 있다(3단계 진입 시 재판단).
4. **입법 harness (스킬)** — 국회 DB(직접 SQL)·법제처 데이터와 WebSearch(사회문제 맥락)를 함께 쓰는 입법 코파일럿(별도 저장소). 입법전문가가 사회문제를 놓고 현황·갭·사법해석·입법이력을 종합해 법안을 고안하도록 돕는다. `legislative-copilot` 프로토타입은 참고만, 새로 구축.

**이 DB가 담지 않는 것 (경계):**
- 시행 중인 **현행법·시행령 본문, 유권해석, 판례** → 3단계(법제처 SDK). 이 DB의 `bills`는 *발의된 의안*만이며 *시행 중인 법*과 구분한다(아래 **법안** 정의 참조).
- **검색/조회 API, 의미 검색, 정책 의제 레이어** → 2단계 이후.
- **사회문제 맥락 수집(WebSearch)** → 4단계 harness.

## Language

**의원 (Member)**:
국회의원. 자연키는 `MONA_CD` (대수 구분 없는 의원 고유 코드). 이름이 같은 동명이인이 있을 수 있어 ID로 식별한다.
_Avoid_: 위원(회의 컨텍스트에서의 호칭만으로 사용), 국회의원(전체 명칭으로 한 번 정도만)

**현직 여부 (Incumbency)** _(도입 예정 — M1)_:
의원이 *현재 재직 중*인지를 나타내는 `members.is_incumbent`(BOOLEAN). 손으로 관리하지 않고, 매 동기화 때 의원 인적사항 API(현직 명부)에 잡히면 TRUE, 안 잡히면 FALSE로 자동 갱신한다. 사퇴·의원직 상실 등으로 떠난 의원도 행은 그대로 두고(`ON DELETE RESTRICT`) `is_incumbent=FALSE`로만 표시해 행적 추적이 끊기지 않게 한다. 시점 정당(`poly_nm_at_vote`)과 같은 "출처에서 파생" 원칙을 따른다(별도 상태 테이블 없음). 사퇴 등으로 명부 동기화 전에 떠난 의원은 프로필 정당(`poly_nm`)이 NULL일 수 있다 — 시점 정당이 필요하면 `votes.poly_nm_at_vote`를 쓰고, 이를 `members.poly_nm`로 덮지 않는다(DECISIONS 2026-06-10).
_Avoid_: 활성/active(DB 활성 행과 혼동), 삭제

**법안 (Bill)**:
국회에 발의된 법률안 또는 의안. 자연키는 `BILL_ID` (`PRC_xxxx` 형식). 보조키는 `BILL_NO` (사람이 읽기 좋은 7자리 숫자, 예: 2218872).
_Avoid_: 법률, 법(이미 통과된 법은 별개 개념), 의안(법안 외에 임명동의안·추천안 등을 포함하므로 더 넓음 — 안건과 구분)

**대표발의자 (Lead Proposer)**:
한 법안의 대표로 이름이 올라가는 의원. 국회 API는 복수 대표발의자를 줄 수 있어 `bill_lead_proposers`에 정규화하고, `bills.rst_mona_cd`는 단일 대표발의일 때의 편의 FK로만 쓴다.
_Avoid_: 발의자(대표/공동 구분 안 됨)

**공동발의자 (Co-proposer)**:
대표발의 외에 이름을 함께 올린 의원들. N:M 관계. `bill_coproposers` 테이블에 정규화.

**표결 (Vote)**:
**본회의 표결만** 다룬다. 위원회 단계의 가결·부결은 API가 제공하지 않아 추적하지 않는다. 본회의 표결 1건 = 그 표결에 기록된 의원 수만큼의 row(실측 285~300, 평균 ~297; 출결·의석 변동으로 가변 — 고정 286이 아니다).
_Avoid_: 의결, 통과, 가결(처리결과의 한 값일 뿐)

**회의 (Meeting)**:
국회 회의록 웹 목록에 노출되고 HTML viewer로 본문 확인이 가능한 한 차 회의 인스턴스. 자연키는 회의록 상세 URL의 `id` 파라미터인 `mnts_id`다.
_Avoid_: 세션(회기와 혼동)

**회기 (Session No)**:
"제434회 국회" 같은 회기 번호. `meetings.session_no`에 정수로 저장 (예: 434). API의 SESS / SESSION_CD에 대응.
_Avoid_: 세션(한국어 대화에서는 회의와 혼동되기 쉬움)

**차수 (Degree)**:
한 회기 안에서의 "제3차" 같은 회의 차수. `meetings.degree`에 원문 텍스트로 저장 (예: '제3차', '개회식'). 정렬용 정수 차수가 필요하면 파생 컬럼을 둔다(스키마는 TEXT).

**회의 안건 (Meeting Agenda Item)**:
국회 원천의 `SUB_NAME`에 들어 있는 회의 상정 항목. 법안도 있지만 임명동의안·출석요구·연설·동의 등이 섞이며, core DB에는 별도 테이블로 보존하지 않고 법안-회의 연결을 만들 때 임시 입력으로만 사용한다.

> **핵심 통찰**: 회의 안건은 회의의 메뉴판이지 본문 섹션이 아니다. API의 `SUB_NAME`은 회의가 다룬 안건 목록을 평탄화한 것일 뿐, 회의록 본문은 안건과 무관한 단일 utterance stream이다. 따라서 회의 안건을 core 검색 엔터티로 두지 않고, 법안으로 식별 가능한 항목만 `meeting_bills`에 남긴다.

**정책 의제 (Policy Topic)**:
사용자가 검색하려는 정책 주제. 예: 전세사기, 의대정원, 채상병 특검, AI 기본법. 회의 안건과 다르며, 향후 `policy_topics` 같은 의미 레이어에서 다룬다.
_Avoid_: 안건(회의 공식 상정 항목과 혼동)

**발언 (Utterance)**:
회의록 본문의 한 발언. 화자(speaker_name + speaker_title)와 시퀀스(meeting 내 순번)로 식별. 의원의 발언은 `speaker_mona_cd`로 의원과 join 가능. 단 매핑되는 건 **의원 직함 발언뿐**(의원 직함 한정 ~100%)이고, 전체 발언 기준 화자-의원 매핑률은 **~61.5%**다 — 나머지 ~38.5%는 장관·국무총리·차관·증인·참고인·전문위원 등 비-의원 화자로 `speaker_mona_cd`가 NULL이다. 비-의원측 조회는 아래 **발언 역할** 정규화로 보강한다.

**주변 발언 창 (Neighbor Window)**:
키워드 hit나 특정 화자 발언의 같은 회의 앞뒤 `sequence` 범위. Q&A 블록, 토론 단위, 안건 단위를 DB에 미리 저장하지 않고 에이전트/API가 발언 stream에서 즉석으로 문맥을 읽는 단위다.
_Avoid_: Q&A 그룹, 세그먼트(저장된 의미 단위처럼 들림)

**발언 역할 (Speaker Role)**:
발언자의 자격을 정규화한 분류: 의원 / 국무위원(장관) / 차관 / 증인 / 참고인 / 전문위원 / 기타. 원천 직함 텍스트(`speaker_title`)는 3,000종 이상으로 흩어져 있어, 이를 소수 역할 enum으로 정규화해 "정부측 발언만", "증인 발언만" 같은 조회를 가능케 한다.
_Avoid_: 직함(raw 텍스트 그대로 — 정규화된 역할과 구분)

**위원회 (Committee)**:
상임위원회 / 특별위원회 / 소위원회. 의원은 시점마다 소속 위원회가 다를 수 있지만, **별도 history 테이블은 두지 않는다** — 위원회 시점은 회의(meetings)와 발언(utterances)에 자동으로 박혀 있기 때문.

**대수 (Assembly Term)**:
"제22대"처럼 4년 임기 단위. 본 DB는 22대(2024-05-30~)만 다룬다. API 파라미터로 `DAE_NUM=22` / `AGE=22` / `ERACO=제22대` 형식이 혼재한다.

**MONA_CD**:
국회의원 고유 코드 (예: `T2T8225E`). 대수에 무관한 의원 식별자. 우리 DB의 `members.mona_cd` PK.

**BILL_ID / BILL_NO**:
- `BILL_ID`: `PRC_D2C6E...` 형식. `bills` PK이자 한 source 안의 식별자. **단, source마다 같은 의안에 다른 BILL_ID를 줄 수 있다** — likms/ALLBILL의 BILL_ID와 우리 `bills`의 BILL_ID가 갈리는 사례 확인(DECISIONS 2026-06-10). BILL_ID를 cross-source 영구키로 가정하지 말 것.
- `BILL_NO`: `2218872` 같은 7자리 숫자. **source 간 안정적인 키.** likms·ALLBILL이 BILL_NO로 조회된다. 의안 동일성 판단·alias 해소의 기준은 BILL_NO다.
- `bill_source_aliases` _(도입 예정 — 이슈)_: source별 BILL_ID를 canonical `bills` row(BILL_NO 기준)에 잇는 정규화.

**mnts_id / confer_num / CONF_ID**:
회의록을 가리키는 식별자가 API마다 형식이 다르다.
- `mnts_id` (정수, 예: 55735): 회의록 상세 HTML URL의 id 파라미터. **회의록의 canonical key로 사용**.
- `CONFER_NUM`: 본회의/위원회 API의 회의번호. mnts_id와 동일한 값.
- `CONF_ID` (예: `N054193`): 별도 회의 식별자. core 검색에는 쓰지 않는 원천 보조키.

**처리결과 (Proc Result)**:
법안의 본회의 처리결과. 가결·부결·대안반영·철회 등. `bills.proc_result`에 텍스트로 저장.

**최종 처리·공포 이력 (Final Outcome)** _(도입 예정 — 이슈)_:
법안의 본회의 의결 이후 정부이송·공포 단계. 공포일·공포번호·정부이송일·법률ID를 ALLBILL에서 `BILL_NO` 기준으로 적재해 `bill_final_outcomes`에 보존한다(DECISIONS 2026-06-10). `bills.law_proc_dt`(법사위 처리일에 가까움)와 **다르다** — law_proc_dt를 공포일로 쓰지 말 것. 현행법 본문은 법제처 단계 소관이고, 이 이력은 거기로 가는 bridge key다.
_Avoid_: law_proc_dt를 공포일로 사용

**대안 관계 (Alternative Relation)** _(도입 예정 — M2)_:
위원회 심사에서 여러 법안 내용을 통합해 새 **대안**(또는 **수정안**)을 만들고 원안들을 *대안반영폐기*(또는 *수정안반영폐기*)할 때, 폐기된 원안과 그 내용을 흡수한 대안/수정안 법안 사이의 연결. `bill_relations`(absorbed_bill_id → alternative_bill_id, relation_type)로 보존한다. 국회 OpenAPI엔 이 관계 필드가 없어, 의안정보시스템(likms) 상세페이지의 `selRefBillId` 숨은 필드를 스크래핑해 채운다(DECISIONS 2026-06-06). 이 연결이 없으면 "이 주제가 과거에 어떻게 입법됐고 무엇이 법으로 남았나"를 추적할 수 없다(대안반영폐기 3,676 + 수정안반영폐기 39건, 통과 대안에 연결고리 없음).
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
각 source가 마지막으로 성공 처리한 기준점. 법안·표결·회의는 날짜 의미가 달라 하나의 global cursor를 쓰지 않고 source별로 분리한다. (개정 2026-06-04: cursor는 fetch 범위를 좁히는 데 쓰지 않고 마지막 성공 시점 관찰용으로만 남긴다 — DECISIONS 2026-06-04 / 이슈 #46.)
_Avoid_: global cursor

**실패 편지 (Dead Letter)**:
재시도 후에도 실패한 API item 또는 회의록 스크래핑 대상. 삭제하지 않고 `pending`/`resolved` 등 상태로 보존해 누락과 지연 적재 원인을 추적한다.
_Avoid_: 터미널 로그만 남기기, 실패 item 무시

**Touched Meeting**:
증분 동기화에서 새로 들어오거나 갱신된 회의. 해당 `meeting_id`만 utterances를 재스크래핑한다.

## 회의 종류 (meeting_type 값)

7가지 enum 값. 각각 다른 OpenAPI 또는 회의 제목 패턴에서 가져온다:

| meeting_type | API 출처 |
|---|---|
| **본회의** | `nzbyfwhwaoanttzje` |
| **상임위** / **특별위** | `ncwgseseafwbuheph` (`CLASS_NAME`·회의명·위원회명으로 구분) |
| **국정감사** | `VCONFAPIGCONFLIST` |
| **국정조사** | `VCONFPIPCONFLIST` |
| **인사청문회** | `VCONFCFRMCONFLIST` |
| **소위원회** | 회의 제목/위원회명 패턴 |

## Relationships

- **의원 ↔ 법안 (대표발의)**: 한 법안에 한 명 이상 **대표발의자**가 있을 수 있다. bill_lead_proposers 정규화 테이블.
- **의원 ↔ 법안 (공동발의)**: N:M. bill_coproposers 정규화 테이블.
- **의원 ↔ 법안 (표결)**: N:M. votes 테이블 (의안 1개당 ~285~300 row, 평균 ~297; 고정 286 아님).
- **법안 ↔ 회의**: N:M. meeting_bills 정규화. 한 법안이 여러 회의에서 다뤄지고, 한 회의가 여러 법안을 다룬다.
- **회의 → 발언**: 1:N. utterances.meeting_id FK.
- **의원 → 발언**: 1:N. utterances.speaker_mona_cd (nullable — 비-의원 화자는 NULL).
- **수집 실행 → 실패 편지**: 1:N. dead_letters.run_id FK.
- **수집 커서 → 수집 실행**: source별 cursor가 마지막 성공 run을 가리킨다.

## Example dialogue

> **PM**: 의원의 위원회 이동 이력을 별도 테이블로 두어야 하나?
> **개발자**: 발언의 위원회는 발언이 속한 회의의 `comm_name`으로 자동으로 안다. 의원의 시점별 위원회 소속 자체에 관심 없다면 별도 테이블 불필요.
> **PM**: 발언 분석만 필요. 빼자.

> **PM**: 안건 단위로 회의록을 잘라서 의미 단위로 만들면 되지 않나?
> **개발자**: 실제 소위원회 회의록을 보면 "다음은 302페이지"처럼 심사자료 페이지와 여러 법안이 섞여 진행된다. 회의 안건은 core 테이블로 두지 않고, 법안으로 식별되는 항목만 `meeting_bills`로 연결하자.

> **PM**: 위원회 단계의 표결 결과도 필요한가?
> **개발자**: API가 본회의 표결만 제공한다. 위원회 표결을 회의록 발언에서 추출하는 건 정밀도가 낮다. 본회의 표결만 다루자.

> **PM**: 2년치 초기 적재와 이후 신규 데이터 추가 코드를 따로 만들까?
> **개발자**: 따로 만들면 drift가 생긴다. 같은 적재 Module을 사용하고, 백필은 전체 범위, 증분 동기화는 source별 cursor + 30일 overlap으로 실행 범위만 다르게 잡자.
>
> *(주: 'cursor + 30일 overlap' 메커니즘은 2026-06-04 폐기 — 증분은 싼 목록 전체 재스캔 + 불변 항목 skip. '같은 Module, mode만 다름' 원칙은 유지. DECISIONS 2026-06-04 / 이슈 #46.)*

## Flagged ambiguities

- **"세션" 다중 의미**: 한국어 대화에서 세션은 회의, 회기, 질의응답 묶음으로 섞이기 쉽다. 본 프로젝트에서는 공식 용어로 **회기**, **회의**, **발언**을 쓰고 "세션"은 피한다.
- **"회의 안건" vs "정책 의제" vs "법안"**: 회의 안건은 국회 회의의 공식 상정 항목, 정책 의제는 사용자가 찾는 주제, 법안은 `BILL_ID`로 식별되는 의안이다. core DB에는 법안과 법안-회의 연결만 보존하고, 정책 의제는 향후 의미 레이어에서 다룬다.
- **"의원" vs "위원"**: 같은 사람이지만 회의 컨텍스트(위원회 회의)에서는 "위원"으로 호칭됨. 화자 직함(`speaker_title`)에 그대로 보존하고, ID(`speaker_mona_cd`)로 의원과 join한다.
- **의원 인적사항 API의 범위**: `nwvrqwxyaytdsfvhu`는 *현직* 의원만 반환하며(관측 시점 286명; 사퇴·재보궐 등으로 변동) 법안·표결 API는 그 밖의 22대 관련 MONA_CD도 참조한다. FK와 JOIN을 보존하기 위해 적재 중 발견한 누락 의원은 최소 이름만 가진 `members` stub으로 보존한다. **현직 여부**(`is_incumbent`)는 이 명부 등장 여부로 판정한다 — 명부에 없는 stub·퇴직자는 FALSE이며, 행은 삭제하지 않는다.
- **회의 식별자 3종**: `mnts_id`(HTML 상세 URL의 id, canonical key), `CONFER_NUM`(본회의/위원회 API의 회의번호, mnts_id와 동일), `CONF_ID`(N0xxxxx, 별도 식별자). 통합 키는 `mnts_id`.
- **대수 파라미터 형식 혼재**: `DAE_NUM=22` (정수) vs `AGE=22` (정수) vs `ERACO=제22대` (한글 텍스트). API별로 다르므로 한 군데 wrapper에서 흡수.
- **회의록 의미 단위**: DB에는 미리 계산한 Q&A/토론/안건 세그먼트를 저장하지 않는다. 향후 SDK나 입법 harness가 필요하면 `utterances`의 `meeting_id + sequence` 주변 발언 창에서 즉석 재구성한다.
- **백필 vs 증분 동기화**: 별도 코드가 아니라 같은 적재 Module의 실행 mode다. 초기에는 로컬/별도 runner가 hosted Postgres DB에 직접 upsert한다.
