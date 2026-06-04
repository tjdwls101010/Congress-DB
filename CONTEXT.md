# Congress-DB

대한민국 국회 22대 임기(2024-05-30~) 데이터를 한 곳에 통합 적재하는 Postgres DB. 의원 한 명을 키로 그 의원의 발의 법안, 본회의 표결, 회의록 발언이 SQL JOIN 한 줄로 나오게 만드는 것이 목적이다.

향후 검색 API/SDK를 그 위에 얹는다. 1차 적재 후 hosted Postgres로 마이그레이션한다.

## 프로젝트 경계 / 로드맵

이 저장소는 4단계 로드맵의 **1단계(국회 데이터 DB)** 만 담는다. 각 단계는 독립 프로젝트이며, 경계를 넘는 기능은 다음 단계로 미뤄 스코프를 묶는다.

1. **국회 데이터 DB** — *이 저장소.* 22대 국회의 발의 법안·본회의 표결·회의록 발언을 정규화 적재.
2. **국회 SDK** — 위 DB 위 조회 계층(별도 저장소).
3. **법제처 SDK** — 현행법령·시행령·행정규칙·법령해석례(유권해석)·판례·헌재결정례를 법제처 OpenAPI에서 제공(별도 저장소). 국회는 API가 흩어져 DB 정규화가 필요했지만, 법제처는 `법령ID` 기반으로 본문·신구대조·체계도가 정연해 live API+SDK로 충분할 수 있다(3단계 진입 시 재판단).
4. **입법 harness (스킬)** — 2·3 SDK와 WebSearch(사회문제 맥락)를 함께 쓰는 입법 코파일럿(별도 저장소). 입법전문가가 사회문제를 놓고 현황·갭·사법해석·입법이력을 종합해 법안을 고안하도록 돕는다. `legislative-copilot` 프로토타입은 참고만, 새로 구축.

**이 DB가 담지 않는 것 (경계):**
- 시행 중인 **현행법·시행령 본문, 유권해석, 판례** → 3단계(법제처 SDK). 이 DB의 `bills`는 *발의된 의안*만이며 *시행 중인 법*과 구분한다(아래 **법안** 정의 참조).
- **검색/조회 API, 의미 검색, 정책 의제 레이어** → 2단계 이후.
- **사회문제 맥락 수집(WebSearch)** → 4단계 harness.

## Language

**의원 (Member)**:
국회의원. 자연키는 `MONA_CD` (대수 구분 없는 의원 고유 코드). 이름이 같은 동명이인이 있을 수 있어 ID로 식별한다.
_Avoid_: 위원(회의 컨텍스트에서의 호칭만으로 사용), 국회의원(전체 명칭으로 한 번 정도만)

**법안 (Bill)**:
국회에 발의된 법률안 또는 의안. 자연키는 `BILL_ID` (`PRC_xxxx` 형식). 보조키는 `BILL_NO` (사람이 읽기 좋은 7자리 숫자, 예: 2218872).
_Avoid_: 법률, 법(이미 통과된 법은 별개 개념), 의안(법안 외에 임명동의안·추천안 등을 포함하므로 더 넓음 — 안건과 구분)

**대표발의자 (Lead Proposer)**:
한 법안의 대표로 이름이 올라가는 의원. 국회 API는 복수 대표발의자를 줄 수 있어 `bill_lead_proposers`에 정규화하고, `bills.rst_mona_cd`는 단일 대표발의일 때의 편의 FK로만 쓴다.
_Avoid_: 발의자(대표/공동 구분 안 됨)

**공동발의자 (Co-proposer)**:
대표발의 외에 이름을 함께 올린 의원들. N:M 관계. `bill_coproposers` 테이블에 정규화.

**표결 (Vote)**:
**본회의 표결만** 다룬다. 위원회 단계의 가결·부결은 API가 제공하지 않아 추적하지 않는다. 본회의 표결 1건 = 의원 286명 모두에 대해 한 row.
_Avoid_: 의결, 통과, 가결(처리결과의 한 값일 뿐)

**회의 (Meeting)**:
국회 회의록 웹 목록에 노출되고 HTML viewer로 본문 확인이 가능한 한 차 회의 인스턴스. 자연키는 회의록 상세 URL의 `id` 파라미터인 `mnts_id`다.
_Avoid_: 세션(아래 두 개념과 충돌)

**회기 (Session No)**:
"제434회 국회" 같은 회기 번호. `meetings.session_no`에 정수로 저장 (예: 434). API의 SESS / SESSION_CD에 대응.
_Avoid_: 세션(Session Group과 헷갈림)

**차수 (Degree)**:
한 회기 안에서의 "제3차" 같은 회의 차수. `meetings.degree`에 정수로 저장 (예: 3).

**회의 안건 (Meeting Agenda Item)**:
국회 원천의 `SUB_NAME`에 들어 있는 회의 상정 항목. 법안도 있지만 임명동의안·출석요구·연설·동의 등이 섞이며, core DB에는 별도 테이블로 보존하지 않고 법안-회의 연결을 만들 때 임시 입력으로만 사용한다.

> **핵심 통찰**: 회의 안건은 회의의 메뉴판이지 본문 섹션이 아니다. API의 `SUB_NAME`은 회의가 다룬 안건 목록을 평탄화한 것일 뿐, 회의록 본문은 안건과 무관한 단일 utterance stream이다. 따라서 회의 안건을 core 검색 엔터티로 두지 않고, 법안으로 식별 가능한 항목만 `meeting_bills`에 남긴다.

**정책 의제 (Policy Topic)**:
사용자가 검색하려는 정책 주제. 예: 전세사기, 의대정원, 채상병 특검, AI 기본법. 회의 안건과 다르며, 향후 `policy_topics` 같은 의미 레이어에서 다룬다.
_Avoid_: 안건(회의 공식 상정 항목과 혼동)

**발언 (Utterance)**:
회의록 본문의 한 발언. 화자(speaker_name + speaker_title)와 시퀀스(meeting 내 순번)로 식별. 의원의 발언은 `speaker_mona_cd`로 의원과 join 가능.

**Q&A 세션 그룹 (Session Group)**:
회의록 안에서 한 의원의 질의 + 정부 답변자의 응답 묶음. 의장이 의원을 호명하는 순간과 답변자 출현을 경계로 자동 감지한다. **본회의와 소위원회에는 적용하지 않는다** (Q&A가 아닌 절차·안건·토론 단위가 섞임).
_Avoid_: 세션(회기와 헷갈림. "그룹" 붙여 구분)

**회의록 세그먼트 (Proceeding Segment)**:
본회의·소위원회처럼 Q&A 세션 그룹이 맞지 않는 회의에서 검토할 수 있는 미래 의미 단위. 본회의는 의사일정·대정부질문·표결 단위, 소위원회는 안건/법안 심사 단위가 후보이며 현재 스키마에는 아직 없다.
_Avoid_: Q&A 그룹(질의자-답변자 묶음과 혼동)

**위원회 (Committee)**:
상임위원회 / 특별위원회 / 소위원회. 의원은 시점마다 소속 위원회가 다를 수 있지만, **별도 history 테이블은 두지 않는다** — 위원회 시점은 회의(meetings)와 발언(utterances)에 자동으로 박혀 있기 때문.

**대수 (Assembly Term)**:
"제22대"처럼 4년 임기 단위. 본 DB는 22대(2024-05-30~)만 다룬다. API 파라미터로 `DAE_NUM=22` / `AGE=22` / `ERACO=제22대` 형식이 혼재한다.

**MONA_CD**:
국회의원 고유 코드 (예: `T2T8225E`). 대수에 무관한 의원 식별자. 우리 DB의 `members.mona_cd` PK.

**BILL_ID / BILL_NO**:
- `BILL_ID`: `PRC_D2C6E...` 형식. 영구 고유 식별자. 자연키.
- `BILL_NO`: `2218872` 같은 7자리 숫자. 사람이 읽기 편한 보조키. 22대 일련번호처럼 보임.

**mnts_id / confer_num / CONF_ID**:
회의록을 가리키는 식별자가 API마다 형식이 다르다.
- `mnts_id` (정수, 예: 55735): 회의록 상세 HTML URL의 id 파라미터. **회의록의 canonical key로 사용**.
- `CONFER_NUM`: 본회의/위원회 API의 회의번호. mnts_id와 동일한 값.
- `CONF_ID` (예: `N054193`): 별도 회의 식별자. core 검색에는 쓰지 않는 원천 보조키.

**처리결과 (Proc Result)**:
법안의 본회의 처리결과. 가결·부결·대안반영·철회 등. `bills.proc_result`에 텍스트로 저장.

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
증분 동기화에서 새로 들어오거나 갱신된 회의. 해당 `meeting_id`만 utterances를 재스크래핑하고 session_groups를 재계산한다.

## 회의 종류 (meeting_type 값)

5가지 enum 값. 각각 다른 OpenAPI에서 가져온다:

| meeting_type | API 출처 | Q&A grouping |
|---|---|---|
| **본회의** | `nzbyfwhwaoanttzje` | ❌ |
| **상임위** / **특별위** | `ncwgseseafwbuheph` (`CLASS_NAME`으로 구분) | ✅ |
| **국정감사** | `VCONFAPIGCONFLIST` | ✅ |
| **국정조사** | `VCONFPIPCONFLIST` | ✅ |
| **인사청문회** | `VCONFCFRMCONFLIST` | ✅ |
| **소위원회** | (별도 API 또는 회의 제목 패턴) | ❌ |

## Relationships

- **의원 ↔ 법안 (대표발의)**: 한 법안에 한 명 이상 **대표발의자**가 있을 수 있다. bill_lead_proposers 정규화 테이블.
- **의원 ↔ 법안 (공동발의)**: N:M. bill_coproposers 정규화 테이블.
- **의원 ↔ 법안 (표결)**: N:M. votes 테이블 (의안 1개당 286 row).
- **법안 ↔ 회의**: N:M. meeting_bills 정규화. 한 법안이 여러 회의에서 다뤄지고, 한 회의가 여러 법안을 다룬다.
- **회의 → 발언**: 1:N. utterances.meeting_id FK.
- **회의 → Q&A 그룹**: 1:N (Q&A grouping 가능한 회의에만). session_groups.meeting_id FK.
- **Q&A 그룹 → 발언**: 1:N. utterances.session_group_id (nullable) FK.
- **의원 → 발언**: 1:N. utterances.speaker_mona_cd (nullable — 비-의원 화자는 NULL).
- **의원 → Q&A 그룹 (질의자)**: 1:N. session_groups.questioner_mona_cd FK.
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

- **"세션" 다중 의미**: 회기(Session No, 제434회) vs Q&A 세션 그룹(Session Group). 본 프로젝트에서는 후자를 항상 "**그룹**" 또는 "**Q&A 그룹**"으로 부른다.
- **"회의 안건" vs "정책 의제" vs "법안"**: 회의 안건은 국회 회의의 공식 상정 항목, 정책 의제는 사용자가 찾는 주제, 법안은 `BILL_ID`로 식별되는 의안이다. core DB에는 법안과 법안-회의 연결만 보존하고, 정책 의제는 향후 의미 레이어에서 다룬다.
- **"의원" vs "위원"**: 같은 사람이지만 회의 컨텍스트(위원회 회의)에서는 "위원"으로 호칭됨. 화자 직함(`speaker_title`)에 그대로 보존하고, ID(`speaker_mona_cd`)로 의원과 join한다.
- **의원 인적사항 API의 범위**: `nwvrqwxyaytdsfvhu`는 현재 286명만 반환하지만 법안 API는 그 밖의 22대 관련 MONA_CD도 참조한다. FK와 JOIN을 보존하기 위해 적재 중 발견한 누락 의원은 최소 이름만 가진 `members` stub으로 보존한다.
- **회의 식별자 3종**: `mnts_id`(HTML 상세 URL의 id, canonical key), `CONFER_NUM`(본회의/위원회 API의 회의번호, mnts_id와 동일), `CONF_ID`(N0xxxxx, 별도 식별자). 통합 키는 `mnts_id`.
- **대수 파라미터 형식 혼재**: `DAE_NUM=22` (정수) vs `AGE=22` (정수) vs `ERACO=제22대` (한글 텍스트). API별로 다르므로 한 군데 wrapper에서 흡수.
- **본회의·소위원회 의미 단위**: "불가능"으로 확정한 것이 아니라, `session_groups`와 다른 Interface가 필요하다고 정리했다. 후보는 본회의의 의사일정/대정부질문/표결 세그먼트, 소위원회의 법안 심사 세그먼트다.
- **백필 vs 증분 동기화**: 별도 코드가 아니라 같은 적재 Module의 실행 mode다. 초기에는 로컬/별도 runner가 hosted Postgres DB에 직접 upsert한다.
