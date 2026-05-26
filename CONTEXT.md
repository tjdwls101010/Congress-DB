# Congress-DB

대한민국 국회 22대 임기(2024-05-30~) 데이터를 한 곳에 통합 적재하는 Postgres DB. 의원 한 명을 키로 그 의원의 발의 법안, 본회의 표결, 회의록 발언이 SQL JOIN 한 줄로 나오게 만드는 것이 목적이다.

향후 검색 API/SDK를 그 위에 얹는다. 1차 적재 후 Supabase로 마이그레이션한다.

## Language

**의원 (Member)**:
국회의원. 자연키는 `MONA_CD` (대수 구분 없는 의원 고유 코드). 이름이 같은 동명이인이 있을 수 있어 ID로 식별한다.
_Avoid_: 위원(회의 컨텍스트에서의 호칭만으로 사용), 국회의원(전체 명칭으로 한 번 정도만)

**법안 (Bill)**:
국회에 발의된 법률안 또는 의안. 자연키는 `BILL_ID` (`PRC_xxxx` 형식). 보조키는 `BILL_NO` (사람이 읽기 좋은 7자리 숫자, 예: 2218872).
_Avoid_: 법률, 법(이미 통과된 법은 별개 개념), 의안(법안 외에 임명동의안·추천안 등을 포함하므로 더 넓음 — 안건과 구분)

**대표발의자 (Lead Proposer)**:
한 법안의 대표로 이름이 올라가는 의원. `bills.rst_mona_cd`에 단일 의원 ID로 저장.
_Avoid_: 발의자(대표/공동 구분 안 됨)

**공동발의자 (Co-proposer)**:
대표발의 외에 이름을 함께 올린 의원들. N:M 관계. `bill_coproposers` 테이블에 정규화.

**표결 (Vote)**:
**본회의 표결만** 다룬다. 위원회 단계의 가결·부결은 API가 제공하지 않아 추적하지 않는다. 본회의 표결 1건 = 의원 286명 모두에 대해 한 row.
_Avoid_: 의결, 통과, 가결(처리결과의 한 값일 뿐)

**회의 (Meeting)**:
국회의 한 차 회의 인스턴스. 5종(본회의·상임위/특별위 일반·국정감사·국정조사·인사청문회)을 `meeting_type` 컬럼으로 구분한다. 자연키는 `mnts_id` (회의록 PDF URL의 id 파라미터로 통합한 정수).
_Avoid_: 세션(아래 두 개념과 충돌)

**회기 (Session No)**:
"제434회 국회" 같은 회기 번호. `meetings.session_no`에 정수로 저장 (예: 434). API의 SESS / SESSION_CD에 대응.
_Avoid_: 세션(Session Group과 헷갈림)

**차수 (Degree)**:
한 회기 안에서의 "제3차" 같은 회의 차수. `meetings.degree`에 정수로 저장 (예: 3).

**안건 (Agenda Item)**:
회의에 상정된 항목. 대부분은 법안(BILL_ID 매핑 가능)이지만, 임명동의안·추천안·연설·동의 등 법안이 아닌 안건도 있어 텍스트도 보존한다.

> **핵심 통찰**: 안건은 회의의 메뉴판이지 본문 섹션이 아니다. API의 `SUB_NAME`은 회의가 다룬 안건 목록을 평탄화한 것일 뿐, 회의록 본문은 안건과 무관한 단일 utterance stream이다. 한 안건 안에서 여러 안건이 일괄 처리되거나 정치적 논쟁이 끼어든다. 따라서 안건 단위로 본문을 분해하지 않는다.

**발언 (Utterance)**:
회의록 본문의 한 발언. 화자(speaker_name + speaker_title)와 시퀀스(meeting 내 순번)로 식별. 의원의 발언은 `speaker_mona_cd`로 의원과 join 가능.

**Q&A 세션 그룹 (Session Group)**:
회의록 안에서 한 의원의 질의 + 정부 답변자의 응답 묶음. 의장이 의원을 호명하는 순간을 경계로 자동 감지한다. **본회의와 소위원회에는 적용하지 않는다** (서로 규칙 없이 대화).
_Avoid_: 세션(회기와 헷갈림. "그룹" 붙여 구분)

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
- `mnts_id` (정수, 예: 55735): 회의록 PDF URL의 id 파라미터. **모든 출처를 통합하는 키로 사용**.
- `CONFER_NUM`: 본회의/위원회 API의 회의번호. mnts_id와 동일한 값.
- `CONF_ID` (예: `N054193`): 별도 회의 식별자. PDF URL과 매핑 안 되니 보조로만 저장.

**처리결과 (Proc Result)**:
법안의 본회의 처리결과. 가결·부결·대안반영·철회 등. `bills.proc_result`에 텍스트로 저장.

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

- **의원 → 법안**: 한 의원이 여러 법안의 **대표발의자**가 될 수 있다 (1:N). bills.rst_mona_cd FK.
- **의원 ↔ 법안 (공동발의)**: N:M. bill_coproposers 정규화 테이블.
- **의원 ↔ 법안 (표결)**: N:M. votes 테이블 (의안 1개당 286 row).
- **법안 ↔ 회의**: N:M. meeting_bills 정규화. 한 법안이 여러 회의에서 다뤄지고, 한 회의가 여러 법안을 다룬다.
- **회의 → 발언**: 1:N. utterances.meeting_id FK.
- **회의 → 안건**: 1:N. agenda_items.meeting_id FK.
- **회의 → Q&A 그룹**: 1:N (Q&A grouping 가능한 회의에만). session_groups.meeting_id FK.
- **Q&A 그룹 → 발언**: 1:N. utterances.session_group_id (nullable) FK.
- **의원 → 발언**: 1:N. utterances.speaker_mona_cd (nullable — 비-의원 화자는 NULL).
- **의원 → Q&A 그룹 (질의자)**: 1:N. session_groups.questioner_mona_cd FK.

## Example dialogue

> **PM**: 의원의 위원회 이동 이력을 별도 테이블로 두어야 하나?
> **개발자**: 발언의 위원회는 발언이 속한 회의의 `comm_name`으로 자동으로 안다. 의원의 시점별 위원회 소속 자체에 관심 없다면 별도 테이블 불필요.
> **PM**: 발언 분석만 필요. 빼자.

> **PM**: 안건 단위로 회의록을 잘라서 의미 단위로 만들면 되지 않나?
> **개발자**: 실제 회의록을 보면 "이상 17건의 법률안을 일괄하여 상정합니다" 식으로 안건이 본문에서 묶여 처리된다. 안건은 회의의 메뉴판이지 본문 섹션이 아니다.

> **PM**: 위원회 단계의 표결 결과도 필요한가?
> **개발자**: API가 본회의 표결만 제공한다. 위원회 표결을 회의록 발언에서 추출하는 건 정밀도가 낮다. 본회의 표결만 다루자.

## Flagged ambiguities

- **"세션" 다중 의미**: 회기(Session No, 제434회) vs Q&A 세션 그룹(Session Group). 본 프로젝트에서는 후자를 항상 "**그룹**" 또는 "**Q&A 그룹**"으로 부른다.
- **"안건" vs "법안"**: 안건이 더 넓다 (법안 + 임명동의안 + 추천안 + 연설 + 동의 등). 코드와 문서에서 구분.
- **"의원" vs "위원"**: 같은 사람이지만 회의 컨텍스트(위원회 회의)에서는 "위원"으로 호칭됨. 화자 직함(`speaker_title`)에 그대로 보존하고, ID(`speaker_mona_cd`)로 의원과 join한다.
- **회의 식별자 3종**: `mnts_id`(PDF URL의 id, 통합 키), `CONFER_NUM`(본회의/위원회 API의 회의번호, mnts_id와 동일), `CONF_ID`(N0xxxxx, 별도 식별자). 통합 키는 `mnts_id`.
- **대수 파라미터 형식 혼재**: `DAE_NUM=22` (정수) vs `AGE=22` (정수) vs `ERACO=제22대` (한글 텍스트). API별로 다르므로 한 군데 wrapper에서 흡수.
