# ERD — Congress-DB (Postgres 16)

9개 핵심 테이블 + source alias 테이블 1개 + final outcome 테이블 1개 + audit 테이블 1개 + 카탈로그 1개 + 수집 운영 테이블 3개. core schema는 향후 검색 API/SDK에서 검색, 필터, 정렬, 조인, 결과 설명에 쓰이는 필드만 보존한다.

## Mermaid 다이어그램

```mermaid
erDiagram
    members ||--o{ bills : "rst_mona_cd"
    members ||--o{ bill_lead_proposers : "mona_cd"
    bills ||--o{ bill_lead_proposers : "bill_id"
    members ||--o{ bill_coproposers : "mona_cd"
    bills ||--o{ bill_coproposers : "bill_id"
    members ||--o{ votes : "mona_cd"
    bills ||--o{ votes : "bill_id"
    bills ||--o{ bill_relations : "absorbed_bill_id"
    bills ||--o{ bill_source_aliases : "canonical_bill_id"
    meetings ||--o{ utterances : "meeting_id"
    meetings ||--o{ meeting_bills : "meeting_id"
    bills ||--o{ meeting_bills : "bill_id"
    members ||--o{ utterances : "speaker_mona_cd"
    ingest_runs ||--o{ dead_letters : "run_id"
    ingest_runs ||--o{ ingest_cursors : "updated_run_id"
```

## Core Tables

### 1. `members` — 의원

국회의원 인적사항. 자연키는 `MONA_CD`.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `mona_cd` | TEXT | **PK** |
| `hg_nm` | TEXT NOT NULL | 한글 이름 |
| `hj_nm` | TEXT | 한자 이름 |
| `eng_nm` | TEXT | 영문 이름 |
| `bth_date` | DATE | 생년월일 |
| `sex_gbn_nm` | TEXT | 성별 |
| `poly_nm` | TEXT | 현재 정당 |
| `orig_nm` | TEXT | 현재 선거구 |
| `elect_gbn_nm` | TEXT | 지역구 / 비례대표 |
| `cmits` | TEXT | 현재 위원회 원문 |
| `reele_gbn_nm` | TEXT | 초선 / 재선 등 |
| `units` | TEXT | 역대 대수 원문 |
| `tel_no` | TEXT | 공개 연락처 |
| `e_mail` | TEXT | 공개 이메일 |
| `homepage` | TEXT | 홈페이지 |
| `mem_title` | TEXT | 약력 |
| `assem_addr` | TEXT | 의원회관 호실 |
| `is_incumbent` | BOOLEAN NOT NULL DEFAULT FALSE | 최신 의원 인적사항 명부 등장 여부에서 파생한 현직 여부 |
| `fetched_at` | TIMESTAMPTZ | 마지막 수집 시각 |

### 2. `bills` — 법안

법안과 의안의 검색 축. 자연키는 `BILL_ID`, 보조키는 사람이 읽기 쉬운 `BILL_NO`.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `bill_id` | TEXT | **PK** |
| `bill_no` | TEXT UNIQUE NOT NULL | 의안번호 |
| `bill_name` | TEXT NOT NULL | 법안명 |
| `propose_dt` | DATE | 발의일 |
| `rst_mona_cd` | TEXT REFERENCES members(mona_cd) | 단일 대표발의 편의 FK |
| `rst_proposer` | TEXT | 대표발의자 원문 |
| `publ_proposer` | TEXT | 공동발의자 원문 |
| `proposer` | TEXT | 제안자 문구 원문 |
| `committee` | TEXT | 소관 위원회명 |
| `committee_id` | TEXT | 소관 위원회 코드 |
| `proc_result` | TEXT | 처리결과 |
| `proc_dt` | DATE | 처리일자 |
| `law_proc_dt` | DATE | 법사위 처리일자 |
| `law_proc_result_cd` | TEXT | 법사위 처리결과 코드 |
| `committee_dt` | DATE | 위원회 회부일자 |
| `cmt_proc_dt` | DATE | 위원회 처리일자 |
| `cmt_proc_result_cd` | TEXT | 위원회 처리결과 코드 |
| `summary` | TEXT | 주요내용 |
| `fetched_at` | TIMESTAMPTZ | 마지막 수집 시각 |

### 3. `bill_relations` — 대안 관계

대안반영폐기·수정안반영폐기된 원안과 그 내용을 흡수한 대안/수정안 법안을 연결한다. 출처는 의안정보시스템(likms) `billDetail.do`의 hidden `selRefBillId`.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `absorbed_bill_id` | TEXT REFERENCES bills(bill_id) | **PK**. 폐기된 원안 |
| `alternative_bill_id` | TEXT NOT NULL | likms `selRefBillId`. 내용을 흡수한 대안/수정안 source key. 현재 `bills`에 row가 있으면 join 가능하나 FK로 강제하지 않는다(DECISIONS 2026-06-06) |
| `relation_type` | TEXT NOT NULL CHECK (...) | `대안반영` / `수정안반영` |
| `source` | TEXT NOT NULL DEFAULT 'likms_selrefbillid' | 관계 출처 |
| `fetched_at` | TIMESTAMPTZ | 마지막 수집 시각 |

### 3a. `bill_source_aliases` — source별 법안 ID alias

source마다 갈릴 수 있는 `BILL_ID`를 안정적인 `BILL_NO`를 경유해 canonical `bills` row로 연결한다. `bill_relations.alternative_bill_id`는 source key로 보존하고, 이 테이블이 canonical 연결을 담당한다.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `source` | TEXT NOT NULL | **PK 일부**. source id의 출처 |
| `source_bill_id` | TEXT NOT NULL | **PK 일부**. source가 제공한 `BILL_ID` |
| `bill_no` | TEXT | source detail에서 확인한 안정 의안번호 |
| `canonical_bill_id` | TEXT REFERENCES bills(bill_id) | 기존 `bills` row. 해소 불가 gap은 row를 만들지 않으므로 nullable |
| `fetched_at` | TIMESTAMPTZ | 마지막 해소 시각 |

### 3b. `bill_final_outcomes` — 최종 처리·공포 이력

ALLBILL이 제공하는 본회의 의결 이후 정부이송·공포 이력을 `BILL_NO` 기준으로 보존한다. `bills.law_proc_dt`는 법사위 처리일자에 가까우므로 공포일로 사용하지 않는다.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `bill_no` | TEXT | **PK**. source 간 안정 의안번호 |
| `plenary_dt` | DATE | 본회의 의결일 (`RGS_RSLN_DT`) |
| `govt_transfer_dt` | DATE | 정부이송일 (`GVRN_TRSF_DT`) |
| `promulgation_dt` | DATE | 공포일 (`PROM_DT`) |
| `prom_no` | TEXT | 공포번호 (`PROM_NO`) |
| `prom_law_nm` | TEXT | 공포 법률명 (`PROM_LAW_NM`) |
| `source` | TEXT NOT NULL | 적재 출처. 현재 `allbill` |
| `fetched_at` | TIMESTAMPTZ | 마지막 수집 시각 |

### 4. `bill_lead_proposers` — 대표발의 N:M

OpenAPI가 복수 대표발의자를 줄 수 있어 정규화한다.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `bill_id` | TEXT REFERENCES bills(bill_id) | **PK 일부** |
| `mona_cd` | TEXT REFERENCES members(mona_cd) | **PK 일부** |
| `order_no` | SMALLINT | 원문 순서 |

### 5. `bill_coproposers` — 공동발의 N:M

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `bill_id` | TEXT REFERENCES bills(bill_id) | **PK 일부** |
| `mona_cd` | TEXT REFERENCES members(mona_cd) | **PK 일부** |
| `order_no` | SMALLINT | 원문 순서 |

### 6. `votes` — 본회의 표결

본회의 표결의 의원별 행. 의안 1건당 의원 수만큼 생성한다.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | BIGSERIAL | **PK** |
| `bill_id` | TEXT REFERENCES bills(bill_id) NOT NULL | |
| `mona_cd` | TEXT REFERENCES members(mona_cd) NOT NULL | |
| `vote_date` | TIMESTAMPTZ NOT NULL | 표결 시각 |
| `result_vote_mod` | TEXT NOT NULL | 찬성/반대/기권/불참 |
| `poly_nm_at_vote` | TEXT | 표결 시점 정당 |
| `session_cd` | INT | 회기 |
| `currents_cd` | INT | 원천 코드 |
| | | **UNIQUE(bill_id, mona_cd)** |

### 7. `meetings` — 회의

HTML 회의록 목록의 한 회의. `total/22.do` 웹 목록이 canonical source이고, OpenAPI는 같은 `mnts_id`가 있을 때 메타데이터 보강에만 사용한다.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `mnts_id` | INT | **PK**. HTML viewer URL의 `id` |
| `title` | TEXT NOT NULL | 회의명/목록 표시명 |
| `meeting_type` | TEXT NOT NULL CHECK (...) | 본회의/상임위/특별위/국정감사/국정조사/인사청문회/소위원회. 예산결산특별위원회·인사청문특별위원회 등은 `meeting_type='특별위'`이고 `comm_name`으로 구분(별도 type 아님) |
| `conf_date` | DATE NOT NULL | 회의일 |
| `comm_name` | TEXT | 위원회명. 본회의는 NULL 가능 |
| `session_no` | INT | 회기 번호 |
| `degree` | TEXT | 제N차 / 개회식 등 |
| `is_temporary` | BOOLEAN NOT NULL DEFAULT FALSE | 웹 목록의 `[임시]` 표기 |
| `is_appendix` | BOOLEAN NOT NULL DEFAULT FALSE | 웹 목록의 `(부록)` 표기 |
| `fetched_at` | TIMESTAMPTZ | 마지막 수집 시각 |

제외 필드: PDF/HWP/VOD/요약 링크, `source_api`, `conf_id`, `class_name`, `comm_code`. 이 값들은 검색 API/SDK의 core query에 쓰이지 않으므로 coverage report, ingest summary, dead letter에서만 다룬다.

### 8. `meeting_bills` — 회의↔법안 N:M

법안이 어떤 회의에서 다뤄졌는지 찾기 위한 핵심 junction. `VCONFBILLCONFLIST`와 `SUB_NAME` 임시 파싱 결과를 합쳐 만든다.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `meeting_id` | INT REFERENCES meetings(mnts_id) | **PK 일부** |
| `bill_id` | TEXT REFERENCES bills(bill_id) | **PK 일부** |

공식 회의 안건 원문은 별도 core 테이블로 보존하지 않는다. 법안이 아닌 안건은 정책 의제 검색과 직접 대응하지 않고, 필요한 경우 향후 의미 레이어에서 evidence 기반으로 모델링한다.

### 9. `utterances` — 발언

HTML viewer DOM에서 파싱한 발언 stream.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | BIGSERIAL | **PK** |
| `meeting_id` | INT REFERENCES meetings(mnts_id) NOT NULL | |
| `sequence` | INT NOT NULL | 회의 내 발언 순번 |
| `speaker_name` | TEXT NOT NULL | 화자 이름 |
| `speaker_title` | TEXT NOT NULL | 화자 직함 |
| `speaker_mona_cd` | TEXT REFERENCES members(mona_cd) | 의원 매핑 nullable |
| `speaker_role` | TEXT NOT NULL CHECK (...) | 의원/국무위원(장관)/차관/증인/참고인/전문위원/기타 |
| `content` | TEXT NOT NULL | 발언 내용 |
| | | **UNIQUE(meeting_id, sequence)** |

## Audit Tables

### `speaker_title_role_map`

원천 `speaker_title`을 어떤 **발언 역할**로 정규화했는지 보존하는 내부 audit 테이블. 외부 조회 interface는 `utterances.speaker_role`이고, 이 테이블은 백필 검증과 추후 역할 승격 검토에 쓴다.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `speaker_title` | TEXT | **PK**. 원천 직함 |
| `speaker_role` | TEXT NOT NULL CHECK (...) | 정규화된 발언 역할 |
| `n_utterances` | BIGINT NOT NULL | 해당 직함 전체 발언 수 |
| `n_no_mona` | BIGINT NOT NULL | `speaker_mona_cd` NULL 발언 수 |
| `n_mona` | BIGINT NOT NULL | `speaker_mona_cd` present 발언 수 |
| `classified_at` | TIMESTAMPTZ NOT NULL | 마지막 분류 시각 |

## Operational Tables

### `api_catalog`

사용 확정 OpenAPI의 작동 여부와 22대 데이터 보유 여부를 기록한다. 회의록 HTML과 웹 목록은 OpenAPI가 아니므로 catalog가 아니라 별도 DOM/coverage 문서에서 관리한다.

### `ingest_runs`

백필, 증분 동기화, dead letter 재처리 실행 단위를 기록한다.

### `ingest_cursors`

source별 증분 기준점. 회의록은 웹 목록 전체 재대조 후 새 `mnts_id`와 임시/부록/title 변화가 있는 touched meeting을 계산한다.

### `dead_letters`

재시도 후에도 실패한 API item 또는 HTML 회의록 대상을 저장한다. 웹 목록에는 있지만 `type=view`가 400인 회의록은 PDF/HWP로 우회하지 않고 여기에서 명시 분류한다.

## 인덱스 후보

```sql
CREATE INDEX idx_members_hg_nm ON members(hg_nm);
CREATE INDEX idx_bills_rst ON bills(rst_mona_cd);
CREATE INDEX idx_bills_propose_dt ON bills(propose_dt DESC);
CREATE INDEX idx_bill_relations_alternative ON bill_relations(alternative_bill_id);
CREATE INDEX idx_coproposers_mona ON bill_coproposers(mona_cd);
CREATE INDEX idx_votes_mona ON votes(mona_cd);
CREATE INDEX idx_votes_bill ON votes(bill_id);
CREATE INDEX idx_votes_date ON votes(vote_date DESC);
CREATE INDEX idx_meetings_date ON meetings(conf_date DESC);
CREATE INDEX idx_meetings_type ON meetings(meeting_type);
CREATE INDEX idx_meetings_comm ON meetings(comm_name);
CREATE INDEX idx_meetings_type_date ON meetings(meeting_type, conf_date DESC);
CREATE INDEX idx_mb_bill ON meeting_bills(bill_id);
CREATE INDEX idx_utterances_meeting ON utterances(meeting_id);
CREATE INDEX idx_utterances_speaker ON utterances(speaker_mona_cd) WHERE speaker_mona_cd IS NOT NULL;
CREATE INDEX idx_utterances_role_meeting_sequence ON utterances(speaker_role, meeting_id, sequence);

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_bills_bill_name_trgm ON bills USING gin (bill_name gin_trgm_ops);
CREATE INDEX idx_bills_summary_trgm ON bills USING gin (summary gin_trgm_ops) WHERE summary IS NOT NULL;
CREATE INDEX idx_utterances_content_trgm ON utterances USING gin (content gin_trgm_ops);
```

## 검색 지원 함수

```sql
search_snippet(source_text TEXT, query_text TEXT, radius INT DEFAULT 80) RETURNS TEXT;
search_bills(query_text TEXT, result_limit INT DEFAULT 50)
  RETURNS TABLE (bill_id, bill_no, bill_name, propose_dt, snippet, similarity_score);
search_utterances(query_text TEXT, result_limit INT DEFAULT 50)
  RETURNS TABLE (utterance_id, meeting_id, sequence, speaker_name, speaker_title, snippet, similarity_score);
```

첫 검색 랭킹은 Postgres `pg_trgm`의 `similarity()` 내림차순이다. 검색 API/SDK는 이 DB 함수 위에서 얇게 시작하고, 벡터/PGroonga는 측정된 recall 실패가 생길 때만 추가한다.
