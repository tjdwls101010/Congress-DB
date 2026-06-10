# DB 업그레이드 분석 — 2026-06-10

다음 세션(이슈 #82·#83·#84·#85·#86 구현)이 참고할 근거 기록.

## 방법

라이브 Neon(`congress-db-staging`)에 직접 붙은 4-에이전트 분석:
- **tracer** — 실제 정책 주제(간호법·전세사기·순직해병)를 원안→대안→표결→회의→발언까지 추적, 막다른 길 탐지.
- **quality** — 결측·고아FK·커버리지·중복을 실측 정량화(데이터 부채 원장).
- **schema** — 인덱스·검색함수·자연키 ergonomics, EXPLAIN.
- **critic** — 위 종합안을 적대적으로 검증(원천 API·likms 직접 호출 포함).

핵심 결론: DB는 **신뢰할 만한 "사실의 출처"**(실 대부분 끝까지 이어짐)이나, 마지막 "법이 됐나"와 증거 선별에서 막힌다. no-SDK 결정(DECISIONS 2026-06-10)으로 DB 자급자족이 더 중요해짐.

## 5대 발견

1. **법률 처리·공포 실 끊김** — 통과 법안 1,593건 중 1,066건이 `law_proc_dt` 결측이고, 관계의 통과 대안 ~720건 *전부* 결측. `law_proc_dt`는 공포일이 아니라 법사위 처리일(570건 present, 전부 `proc_dt`보다 이전). 공포일 자체는 DB에 없음. → 이슈 #86.
2. **BILL_ID 교차-source 분기** — `bill_relations`의 130개 "missing" 대안은 **15개 distinct source id**로 압축, 15/15가 *같은 BILL_NO로 이미 `bills`에 존재*하되 *다른 BILL_ID*. likms/ALLBILL은 BILL_NO로 조회. BILL_NO가 안정 키, BILL_ID는 source마다 갈림. → 이슈 #82.
3. **speaker_role 부재** — 비의원 발언 530,769건(38.51%)이 raw `speaker_title` 3,124종으로만 존재. 역할 필터 불가. → 이슈 #83.
4. **떠난 의원 프로필 결측** — 정당 NULL 의원 20명(추미애 등)은 2026-06-04 지방선거/재보궐로 사퇴 → 현직 명부 API에 없음. `is_incumbent=false`는 정확. `poly_nm`만 NULL → 시점정당은 `votes.poly_nm_at_vote` 사용(이슈화 안 함, DECISIONS 2026-06-10).
5. **요약 결측** — `summary` 253건(212 표결有, 241 회의有). → 이슈 #84.

## 데이터 부채 원장 (quality 실측)

| 부채 | 수치 | 영향 harness 질문 | 심각도 | 비고 |
|---|---:|---|---|---|
| 통과 법안 `law_proc_dt` 결측 | 1,066 / 1,593 | 통과→공포 연결 | H | ALLBILL로 해소 (#86) |
| 관계 통과 대안 공포 결측 | ~720 distinct | 대안이 법 됐나 | H | #86 |
| alternative target missing | 169 (130 대안 + 39 수정안) | 대안 추적 | H | 130=15 source id, BILL_NO alias로 해소 (#82); 39는 detail 부재 → accepted-gap |
| `propose_dt` 결측 | 1,028 (모두 표결有) | 시간축·정렬 | H | (대안)(위원장) 726, ALLBILL `PPSL_DT`로 backfill (#86) |
| `speaker_role` 부재 | raw title 3,124, NULL 발언 530,769 | 정부/증인 발언 필터 | H | #83 |
| `summary` 결측 | 253 | 요약 검색 recall | M~H | #84 |
| 상임위 `meeting_bills` 커버리지 | 510/894 = 57.05% | 회의↔법안 | WEAK | 무연결 회의 상당수 국정감사·현안질의(측정 착시) — 백로그 |
| 의원 프로필 stub | 20 (고활동 포함) | 의원 정당/현직 | — | 떠난 의원, is_incumbent 정확; 백로그 |
| FK 고아 | 0 (169 의도 제외) | — | — | 표결·고아 정합성 견고 |

## 검색·구조 사실 (schema 실측, EXPLAIN)

- FK 인덱스 누락 없음. 기본 JOIN 경로 빠름(발의 4.3ms, 표결요약 0.29ms, 주변발언 1.7ms).
- `search_bills('전세사기',20)` 19.3ms, `search_utterances('전세사기',20)` 208.9ms — 둘 다 pg_trgm GIN 사용(성능 정상). 검색 갭은 *성능*이 아니라 *기능*(역할/회의메타 필터 없음).
- 한 회의에 최대 45개 법안 연결(평균 32, p99 290) → "이 발언=이 법안 증거"는 과잉주장 위험(소비자/스킬이 fanout 인지해야 함).
- 동명이인 `박지원` 2명 → 이름은 key 아님, `mona_cd`/`bill_no`/`mnts_id` 등 evidence key 보존.
- `votes.vote_date`는 `TIMESTAMPTZ` → 날짜 비교는 `(vote_date AT TIME ZONE 'Asia/Seoul')::date` (naive UTC 캐스팅 시 5,058행이 하루 전으로 보이는 착시; KST 기준 mismatch 0).

## 제안 판정 → 이슈 매핑

| 제안 | 판정 | 결과 |
|---|---|---|
| 법률 처리·공포 bridge (ALLBILL) | SOLID/H | **#86** |
| BILL_ID source alias | SOLID/H | **#82** (#86 차단) |
| speaker_role | SOLID/H | **#83** |
| summary backfill | SOLID/M~H | **#84** |
| read-only DB role (no-SDK 안전) | SOLID | **#85** |
| 의원 stub repair | WEAK | 백로그(떠난 의원, poly_nm_at_vote로 대체) |
| 검색함수 v2 | WEAK | 백로그(스킬이 직접 SQL; 반복되면 승격) |
| meeting_bills 커버리지/provenance | WEAK/CUT | 백로그(provenance 테이블은 금도금) |

## 전체 원자료

per-agent 상세 보고서(쿼리·수치·EXPLAIN 원문): `tmp/codex-analysis/{tracer,quality,schema,critic}/report.md` (로컬, gitignore). Neon 접속: `.env.local`(gitignore).
