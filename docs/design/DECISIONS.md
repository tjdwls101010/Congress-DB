# Decisions

Newest first. Each entry: `## YYYY-MM-DD — short title`, then 1-3 sentences
(context + decision + why).

## 2026-06-18 — 외부 공개 읽기: congress_ro 연결문자열 공개 채택 + Data API 락다운 + RLS 재활성화 함정 수정

PM이 "쓰기는 나만, 읽기는 누구나"로 DB를 외부 공개하기로 결정. 세 가지를 처리했다.

**(A) Data API의 anonymous/authenticated 과다권한 락다운** (`db/roles/data_api_public_read.sql`, Neon 적용·멱등): Data API(PostgREST)는 `congress_ro`가 아니라 Neon이 만든 `anonymous`·`authenticated` 역할로 동작하는데, Neon이 프로비저닝 시 `authenticated`에 **전 테이블 arwd(쓰기 포함) + 미래 테이블 자동부여(default privilege)**를 깔아둬 — JWT만 얻으면 데이터 수정/삭제·내부 ops/raw 열람이 가능한 위험이 있었다. 조치: 위험한 default privilege 제거 + 현재 전권 회수 → 둘을 `congress_ro`와 동일 읽기 allowlist(12객체 SELECT + 검색함수 3개)로 한정. `SET ROLE anonymous` 실증: 읽기/검색 OK, 내부테이블·모든 쓰기 차단.

**(B) "무인증 공개"의 실제 = 연결문자열 공개로 채택.** Neon Data API는 **헤더 없는 순수 접근을 지원하지 않는다** — 공식 문서 "Anonymous access still uses a JWT"(로그인 없이 자동발급되는 *익명 JWT*가 필요, 토큰 0은 항상 거부). 또 PostgREST는 자유 SQL이 아니라 REST 필터/정렬/RPC만 된다. 프로젝트 목표가 "직접 SQL 자유 활용"이라 PM은 **읽기전용 `congress_ro` 연결문자열을 공개 read-key로 배포**하는 길을 택했다(no-SDK 목표와 일치, 어떤 Postgres 클라이언트로든 로컬처럼 자유 SQL). 데이터는 전부 공개 사실이고 PII는 015에서 DROP돼 안전. 남용 대비 `congress_ro`에 `statement_timeout=60s` 캡. **저장소가 private이라 연결문자열은 별도 공개 채널로 배포**해야 외부인이 쓴다(`docs/design/DB-ACCESS.md` 공개 읽기 절). HTTP가 필요한 소비자를 위해 Data API도 병행 가능(락다운 완료).

**(C) ⚠ RLS 재활성화 함정 발견·수정 (가장 중요).** Data API/Neon Auth 셋업이 **소비자 10개 테이블에 RLS를 자동 재활성화**(정책 0개)해 027을 되돌려 놨다 — owner는 테이블 소유자라 우회해 멀쩡히 보이지만 **congress_ro·anonymous는 모든 base 테이블을 0행으로** 봤다(뷰는 owner 권한 실행이라 정상 반환 → 더 헷갈림). 즉 연결문자열을 공유했어도 모두가 *조용한 빈 결과*를 받을 뻔했다(PM이 "실제로 읽히나" 물어 발견). 수정: 12개 소비자 테이블 RLS DISABLE(027 재적용, bills COMMENT는 029 보존 위해 미변경), `data_api_public_read.sql`에 RLS-off도 합쳐 "한 스크립트로 공개읽기 복구"로 만듦. 검증: congress_ro bills 18,361·search 정상, anonymous 동일. **교훈: Data API(RLS 기반 보안 모델)와 이 프로젝트의 RLS-off+GRANT 모델은 충돌한다 — Data API 설정을 만질 때마다 RLS가 다시 켜질 수 있다.** 라이브 회귀팩(`make regression-pack`, congress_ro로 floor 체크)이 재발 시 "0 < floor"로 FAIL해 잡으니, Data API 손댄 뒤엔 회귀팩을 돌리고 FAIL이면 `data_api_public_read.sql`을 재실행한다.

## 2026-06-18 — 직접-SQL 3차 독립 재검증(시뮬레이션 렌즈): 2글자 검색 성능 절벽 + 생애주기/네이밍 COMMENT (migration 029)

7차원 감사(028) 후, "차가운 직접-SQL 사용자/입법전문가 스킬이 schema+COMMENT+가이드만으로 실제 어려운 질문을 끝까지 푸는가"를 라이브로 시뮬레이션하는 다른 렌즈로 3차 재검증(ultracode 32 에이전트, end-to-end 16질문 + 각 마찰점 적대 검증 + EXPLAIN). 이전 두 라운드가 못 본 결함을 발굴 — 전부 COMMENT/doc 레이어, 스키마·데이터 변경 0. **결정 — migration 029(COMMENT-only, 멱등, local+Neon 적용):** (1) **must-fix: 검색 2글자 성능 절벽** — `search_utterances`/`search_bills`는 pg_trgm(3-gram) 기반이라 2글자 한국어 질의는 GIN 인덱스를 못 타고 Seq Scan으로 떨어진다(utterances 138만행 2글자=9.4초로 statement_timeout 초과 위험, 3글자+는 0.8초; bills 0.6초 vs 0.1초) — 함수 COMMENT에 '3글자+ 정식명 확장·결과==limit이면 절단 의심' 추가(기존 COMMENT는 recall 천장만 다뤘음). 인덱스로는 해결 불가(3-gram 본질). (2) `bills` 테이블 COMMENT에 **생애주기 단계 시간순 파이프라인** 한 줄 추가 — 개별 컬럼 COMMENT는 정확했으나 순서가 한 곳에 없고 물리 컬럼 순서가 시간순과 거꾸로(proc_dt가 committee_dt보다 앞)라 introspect-only 사용자가 오독. (3) `promulgation_dt` COMMENT 거부권 후보 수치 **27→26 정정**(IS DISTINCT FROM이 plenary NULL 1행을 오산입, 정답은 plenary_dt>proc_dt=26 — plenary_dt COMMENT와 일치). (4) `bill_meeting_contexts` fanout 수치에 **'회의당'** 단위 명시(뷰 행 그대로 avg하면 145로 보여 COMMENT가 틀린 듯 오판). (5) `members.sex_gbn_nm`(NULL 20=stub, GROUP BY NULL 버킷)·`meetings.meeting_type`(CHECK 7종, 인사청문회 적재 0) COMMENT 신규. (6) `members.hg_nm` 동명이인 식별축을 불안정한 '표결수'에서 `bth_date·orig_nm·units`로 교체. **doc:** DB-QUERY-GUIDE §0에 중점 정규화(U+318D→U+00B7 translate) 추가, Q2에 거부권후보 컬럼(미공포 59=거부권 26+계류 33), Q5에 위원회↔회의 두 경로(comm_name=자체회의 / committee_id→meeting_bills→meetings=소관법안 다뤄진 회의, fanout은 count(DISTINCT)) 추가, HOSTED-POSTGRES-MIGRATION.md에 no-SDK 피벗 historical note(SDK 잔재). 회귀 가드: search 함수 COMMENT '3-gram'·bills '생애주기 단계'·promulgation_dt '거부권'·sex_gbn_nm 등 키워드 잠금. 211 passed·회귀팩 4/4 PASS. **남은 보류는 028과 동일**(speaker_title trigram 인덱스). 교훈: 성숙한 DB의 잔존 결함은 dimension 감사가 아니라 "실제로 끝까지 풀어보는" 시뮬레이션 + EXPLAIN으로만 드러난다(2글자 절벽은 코드/스키마 읽기로 안 보임).

## 2026-06-18 — 직접-SQL 소비자 7차원 감사: 잔존 함정은 전부 doc/COMMENT 레이어, 공포 bridge 키는 prom_no

직접-SQL 소비자(사람·AI agent) 관점에서 7차원(생애주기·공포 bridge·문서정합·질의용이·데이터품질·네이밍·인덱스) 적대 감사(ultracode 36 에이전트, 라이브 Neon RO 교차검증)를 돌렸다. **결론: B+ — 데이터/스키마/인덱스/권한 구조는 앱 층을 올리기에 충분하고 잔존 결함이 0건의 하드-투-리버스 스키마 변경, 전부 doc/COMMENT 레이어다.** 모든 수치는 직접 재검증. **결정 — "에러 없는 조용한 오답/누락" 함정 3종을 COMMENT/doc로 막는다**(migration 028 + doc): (1) **공포→법제처 bridge 키는 `prom_no`(공포 1,365건 100% 채움)** — `prom_law_nm`은 단독 사용 금지(66건 NULL=위원장 대안 신규 제정법, 이름 있는 1,299 중 648/~50%가 공백 제거형이라 법제처와 exact-match 불가, 같은 법이 DB 안에서 공백 有/無 공존). 저장값은 변형하지 않고(raw fidelity) 매칭 시 양쪽 공백 제거·이름 NULL이면 `bills.bill_name` 폴백. (2) `committee_dt`/`cmt_proc_dt`/`law_proc_dt`는 (대안)·(정부) 법안에서 체계적 NULL(가결 1,593 중 committee_dt 64%·law_proc_dt 67%, 대안 740·정부 196은 세 컬럼 100% NULL)이라 lifecycle 필수 단계로 가정 금지. (3) `bill_lineage`는 proc_result(본회의) 기준이라 소관위-종료 대안반영폐기 원안 487건(proc_result NULL, cmt_proc_result만 대안반영폐기)이 부재 — 0행이 미흡수 아님(뷰 COVERAGE COMMENT). 함께: 발의자 정당 NULL 20명(전원 이탈 의원, votes.poly_nm_at_vote로 복구)을 `bill_coproposers` COMMENT로 경고, 죽은 `committee_id=9700007` 쓰던 Q5를 안정·UNIQUE `committee_name` 필터로 교체, 동명이인(박지원 2명) 쇼케이스 레시피를 mona_cd 우선으로, stale doc 마커(is_incumbent·bill_source_aliases·degree) 제거. COMMENT가 다시 덮이지 않도록(과거 026이 013을 덮음) 함정 키워드 존재를 `test_critical_gotcha_comments_carry_their_warning`로 잠갔다. **보류(질문)**: `utterances.speaker_title` trigram 인덱스는 단독 ILIKE만 빠르고 문서화된 IA S6(LATERAL+ORDER BY)를 228ms→842ms로 퇴행시켜 적용하지 않음 — 탐색적 직함검색 수요가 입증되면 S6 플랜 회귀 확인 후 재판단.

입법전문가 소비 관점에서 전 소비자 표면(12 테이블)을 적대적 deletion-test(라이브 SQL 다중 에이전트 워크플로: outcomes·relations·10테이블 sweep·검색 recall)로 감사했다. 결론: 스키마는 이미 lean하며 진짜 잉여는 소수다. **결정** — (1) `bill_relations`+`bill_source_aliases`를 ops로 REVOKE하고, 소비자에겐 direct+alias 해소를 캡슐화한 **`bill_lineage` 뷰**를 노출한다(미해소 alternative=NULL 포함). 대안 A(`bills` self-FK = 80% NULL 희소컬럼)·B(canonical 물질화 = 단일진실원천 깨고 drift)보다 뷰(C)가 deep-module·가역·단일진실원천이라 채택. (2) `members.elect_gbn_nm`(`orig_nm`서 100% 도출) DROP. **`bill_relations.relation_type`은 구현(2026-06-14, #125) 중 KEEP으로 정정** — 같은 슬라이스의 REVOKE가 이미 bill_relations를 소비자 introspection에서 제거하므로 물리 DROP의 *소비자* 이득은 0인 반면, 이 컬럼은 ETL이 *사용 중*(`ingest_bill_relations` 기록·`bill_source_aliases` owner-연결 진단 읽기)이라 DROP은 ETL 2개+테스트 4개를 고치게 만드는 순부담이다. REVOKE가 이 컬럼을 소비자→ETL/ops(META층, 사용 중이면 KEEP)로 재분류한 것이고, 소비자는 뷰가 `proc_result`에서 파생한 relation_type을 그대로 받는다(물리 컬럼 유무 무관). (3) 현존 데이터 함정 COMMENT 추가 — 발의주체(가결 법안 64%가 lead 없음 = 위원장 대안→`bill_lineage`·정부제출), 동명 법안(distinct 3,683/18,361), 검색 recall 천장, 거부권 추론. **KEEP 확정**: `bill_final_outcomes`(공포·거부권 비도출, 가결 1,593 중 228 미공포 식별), `committees`(31행 dimension은 인라인 시 18k 중복), `utterances.speaker_role`(3,124종 직함→7 enum L4 정규화 — 적대검증이 naive drop서 구제), `order_no`, `prom_law_nm`(비용0 보류). **검색**: `search_bills`/`search_utterances`는 실은 ILIKE substring(trigram은 정렬만)이고, tsvector FTS는 한국어 형태소 분석기 부재로 recall이 ILIKE에 strictly dominated(옮기면 반토막)이라 ILIKE 유지. recall 손실은 별칭(노란봉투법→0건, 통계적 도달 불가)·동의어 갭이며 DB가 아닌 **스킬 inform(별칭사전·질의확장)** 영역, 50-cap은 호출측 limit으로 완화. 세 정책주제 풀워크플로 리허설(전세사기·노조법·AI 기본법)에서 DB가 국회 다리로 충분함을 입증했다(못 한 건 전부 법제처/websearch 핸드오프 또는 inform). **Demand-gate 백로그**(통시성·법안 본문·위원회 membership·청원/공청회/입법예고·띄어쓰기 FTS·의미검색)는 스킬 프로토타입이 수요를 입증할 때 재개방. 구현은 이슈로 분리(bill_lineage restructure / elect_gbn_nm / gotcha COMMENT), 다음 세션.

## 2026-06-13 — 위원회는 정규화 후 중복명 삭제, proposer는 raw wording으로 보존

#117 결론: `bills.committee`는 `committee_id -> committee_name` 31개 pair가 현재 1:1이라 `committees(committee_id, committee_name)` dimension을 먼저 만들고 `bills.committee_id` FK를 건 뒤 중복 display column을 삭제한다(#120). 반대로 `bills.proposer`는 `외 N인` 등 join으로 복원되지 않는 원천 문구라 삭제하지 않고 `proposer_raw`로 rename해 정규화 proposer relation과 역할을 분리한다(#121).

## 2026-06-13 — 삭제 우선 스키마 정리 2차: redundant fields are removed, ops fields are hidden

PM이 Neon 비용과 direct-SQL 스킬 표면을 기준으로 "불필요하면 숨길 게 아니라 삭제"를 재확인했다. 결정: `bill_lead_proposers`가 정본인 `bills.rst_mona_cd`와 현재 자연키 `(bill_id,mona_cd)`로 충분한 `votes.id`는 삭제 대상으로 승격하고, `congress_ro`는 broad grant가 아니라 allowlist로 고정한다. 반대로 `bills.proposer`(raw `외 N인` 정보), `bills.committee`(정본 committee mapping 전까지 표시명 보존), `fetched_at`(운영 감사), `proc_result`/`cmt_proc_result`(서로 다른 처리 단계), `bill_source_aliases`(source key bridge), `utterances.id`(현재 search interface)는 유지한다.

## 2026-06-12 — 미사용 ops 테이블 2개 물리 삭제 (api_catalog·speaker_title_role_map)

015에서 REVOKE로 소비자에게 숨긴 5 ops/audit 테이블 중, **파이프라인 의존이 없는 둘만 물리 삭제**(migration 016, PM 결정 — 저장 절감은 수백KB로 미미하나 깔끔함 위해). `api_catalog`(11행, `core/endpoints.py` PIPELINE_ENDPOINTS 상수의 DB 거울일 뿐)는 렌더러가 상수를 직접 읽도록 재지정(`API-CATALOG.md`는 DB 없이 생성 유지)하고 테이블 쓰던 seed/verify 모듈·스크립트·Makefile 타깃 제거. `speaker_title_role_map`(3,124행, utterances GROUP BY로 100% 도출)는 백필이 더는 영속화 안 함(speaker_role 백필 자체는 유지). 나머지 셋(`ingest_runs`·`ingest_cursors`·`dead_letters`)은 **유지** — 22대 진행 중 증분 수집·재시도 안전망이라 파이프라인이 실제 사용. 마이그레이션 모델이 매번 전체 재실행(추적 테이블 없음)이라 008/011/015의 죽은 테이블 참조(CREATE·COMMENT·REVOKE)도 정리; `make db-reset` 전체 체인 클린(14 테이블). 194 passed. ETL/렌더러/test 동기화는 supervised Codex.

## 2026-06-12 — 소비자 스키마 정리: 중복·죽은·이름거짓 필드 18개 DROP + ops 5테이블 REVOKE

소비자(입법전문가 스킬)가 introspect하는 스키마 표면 자체가 소비자 컨텍스트라, 노이즈 필드가 추론을 흐린다(skill-creator 'irrelevant text degrades the model'를 DB에 적용). 16-테이블 심층 설계 감사 2회(워크플로, 33+30 에이전트, 반증 검증)로 *소비자/회귀/뷰가 읽지 않고 전부 재도출 가능한* 것만 제거(migration 015). DROP: bills(rst_proposer·publ_proposer = join string_agg 정확중복, law_proc_result_cd = 96.9% NULL 죽음), members(tel_no·e_mail·homepage·assem_addr = 연락처 directory, reele_gbn_nm = units 토큰수 도출, cmits = 84.7% NULL '현재 위원회'라 거짓·특위 노이즈, mem_title = HTML 약력 blob), votes(session_cd = meetings.session_no 도출, currents_cd = 불투명 죽은 원천코드), meetings(is_appendix·degree·is_temporary = title 파생 웹목록 잔재), bill_relations·bill_final_outcomes(source = 단일 상수). RENAME bills.cmt_proc_result_cd→cmt_proc_result(_cd인데 라벨 담는 거짓이름 — 728건 소관위-사망 신호라 keeper). REVOKE SELECT(api_catalog·ingest_runs·ingest_cursors·dead_letters·speaker_title_role_map) → 소비자 introspection 17→12. + legibility COMMENT 14개(동명이인·선수도출·서명순서·생존편향·fanout 등). 이때는 drop 권한 **bills.committee·rst_mona_cd·canonical_bill_id는 KEEP**으로 봤지만, 2026-06-13 삭제 우선 재감사에서 `rst_mona_cd`만 제거로 supersede했다. `bills.committee`·`canonical_bill_id`는 여전히 유지. ops 내부 죽은 NULL컬럼·api_catalog 물리삭제는 REVOKE로 소비자에게 안 보이니 별도 ops 위생으로 deferred. ETL/schema/test 동기화는 supervised Codex(로컬 docker 테스트), 201 passed.

## 2026-06-12 — 소비층을 COMMENT+schema로 일원화, DB-QUERY-GUIDE는 cross-table 레시피만

PM이 소비-원칙(모델 지능 신뢰, hard-rule이 아닌 inform)을 직접 적용해 짚었다: 어떤 필드로 무엇을 추론하는지를 *문서*로 명시하는 것은 (a) 구조(타입·FK)는 `schema.sql`+introspection에 이미 있어 중복이고, (b) 통째 SQL 레시피는 Claude의 SQL 지능을 불신하는 over-specification이며, (c) 별도 레포 markdown은 다른 코드베이스의 스킬로 따라가지 않는다. 감사 결과 가이드의 함정 8개·어휘·커버리지가 *전부 이미 COMMENT/`schema.sql`에* 있었다. 결정: 함정·어휘·구조는 COMMENT+schema(DB와 함께 이동, `\d+`로 introspect)에 일원화하고, `DB-QUERY-GUIDE.md`는 introspection이 조립 못 하는 **cross-table 패턴만**(Q2 공포완전성·Q9 alias해소·Q11 fanout뷰·Q12 소관위정규화) 남겨 224→~70줄로 축소했다(COMMENT가 가리키는 Q2·Q12 번호는 유지, 새 마이그레이션·데이터 변경 없음). 이로써 'inform'은 별도 hard-rule 문서가 아니라 모델이 introspect하는 in-DB 자기설명 + 소비자 지능이 된다. 기존-데이터 소비 준비는 이로써 종료 — 추가 DB 작업은 스킬 프로토타입이 실제 수요를 드러낼 때(prototype-gated).

## 2026-06-12 — bill_documents(#96) 적재 후 되돌림: 신규 소스는 prototype-gated

법안 문서 URL inventory(`bill_documents`, BILLRCPV2)를 구현·머지·Neon 적재(21,494행)했다가 같은 날 되돌렸다(Neon+로컬 `DROP TABLE` + main revert). 이유: #96은 Tier C **신규 소스**인데 demand-gated 원칙(2026-06-11)상 신규 소스는 스킬 프로토타입이 수요를 입증할 때까지 prototype-gated여야 한다 — 프로토타입이 없어 "스킬이 문서 링크를 실제로 쓰는가"가 미입증인 채 적재한 건 원칙이 금지하는 추측성 [1]이었다(게다가 `link_url`은 `bill_id`로 파생 가능해 저장조차 불필요). 이슈 #96은 prototype-gated로 재개방(BILLRCPV2 방법·필드 매핑은 이슈에 보존) — 프로토타입이 수요를 입증하면 재구축. 교훈: "신규 소스/구조"(Tier C)를 "안전 가드레일"(Tier A)로 오분류해 demand-gate를 건너뛰지 말 것.

## 2026-06-11 — 소비 적합성 원칙: 소비자 지능을 신뢰, materialize 아닌 inform

DB는 소비자(입법전문가 스킬 속 Claude)가 멀티키워드 검색으로 *도출할 수 없는* 구조·관계 사실만 담는다(교차소스 ID 조인·원안→대안→공포 lineage·공포 사실·정규화 엔터티). 소비자가 스스로 도출 가능한 어휘 변형(콜로퀴얼→공식명)·판정(증거강도·is_government·의안종류)은 DB가 떠안지 않고 검색 표면(`search_*`) + COMMENT/쿼리가이드 caveat로 *알린다*. 3-에이전트 독립 감사(구현 스키마/M3 이슈/문서)가 구현 DB는 이 원칙에 이미 정렬됨을 확인(session_groups·agenda_items 제거, 판정 불리언 거부, membership 게이팅); 미구현 M3에서 #91 evidence 버킷·#94 committee(이미 `bills.committee_id` 존재)·#93 affiliation 판정·#97 ops-카탈로그를 정리(materialize→inform/축소). skill-creator의 'hard-rule이 아닌 principle로 모델 지능을 신뢰' 통찰을 데이터 설계에 적용한 것.

## 2026-06-11 — DB upgrades become demand-gated by a regression pack + skill prototype, not speculative additions

A 4-persona analysis round (demand / connect / source / critic, run as parallel Codex against live
Neon) converged: after #82–#86 the DB's *facts* are largely sufficient (원안→대안→공포 chain ~closed —
3,676/3,715 relations canonical, 3,674 with outcomes), and the remaining gaps are mostly
[3 법제처] / [4 skill-layer] boundary or **consumption packaging / over-claim guardrails**, not
missing facts. The critic argued — and I agree — that continuing to upgrade the DB *before* the
입법전문가 skill exists is increasingly the wrong order: the real residual demand depends on the
skill's dialog flow and query strategy, which can't be known until it's prototyped. Decision:
(1) the next implementation round **leads with a 4-scenario retrieval regression pack**
(전세사기·의대정원·AI 기본법·채상병 특검) — a schema-free read-only pass/fail harness that anchors every
further DB change to a real query the skill would issue (the "feedback loop first" discipline applied
to the DB); (2) a **skill dialog-flow prototype** then runs against the live DB, and only query
failures that are genuinely [1] (missing source fact / SQL ergonomics, not [3]/[4] boundary)
graduate into DB work; (3) larger [1] candidates (lifecycle views, new sources) are written as
issues now but **prototype-gated** — issued, not built blind. Every finding is boundary-tagged
[1 congress-db] / [3 법제처] / [4 skill]; [3]/[4] items are roadmap backlog, not this-repo issues.
Reversible — if the prototype reveals a broad structural need, a bigger DB round can follow.

## 2026-06-11 — Committee becomes a first-class dimension; committee *membership* stays gated on source verification

Every anchor scenario needs "who sits on the 소관 위원회" (국토위/법사위/복지위/과방위), which the DB cannot
answer: `members.cmits` is populated for only 49/320 members and committee identity is scattered as
inconsistent strings across `bills.committee(_id)` (31 names) and `meetings.comm_name` (38 names, only
24 overlapping, with spacing-variant duplicates). Decision: (1) build a **committee dimension**
(canonical names + aliases derived from existing strings — low risk, no new source) now; (2) committee
**membership** (who is on which committee) is **not built** until a source-verification slice proves
the roster API `nktulghcadyhmiqxi` returns full, stable committee rosters — it returned only 34 rows
with no_data for major standing committees, so ingesting it now would be guessing. If verified, the
PRD's deliberate `member_committees` exclusion is formally revisited. Why: high skill demand justifies
reopening the exclusion, but an unreliable source must not be ingested on a guess.

## 2026-06-11 — 의안유형 (bill_kind) is name-derived and consolidated with the promulgation-bridge ledger

`bills` mixes 법률안 with non-law 의안 (감사요구안 15·수사요구안 3·규칙안 2·결의안 20·동의안 31·승인안 4 ≈ 75 of
18,361), but the source bill-list API exposes no 의안종류 field, so a classifier must derive type from
`bill_name` — non-trivial because law bills appear as 법률안 / 법안 / 특별법안 / 특별조치법안 / 전부개정법률안.
Decision: a tested name-based classifier (`bill_kind`, carrying provenance) is built **together with**
the promulgation-bridge completeness ledger, because the same fact — "is this a 법률안?" — is what
distinguishes an expected-no-공포 의안 from a genuine `prom_law_nm` gap (66 promulgated rows lack a law
name; 294 is the gross blank count including not-yet-promulgated). "Passed but no 공포" is normal for a
non-law 의안, a real gap only for a 법률안. Derived law names are candidates, never overwrites of source.

## 2026-06-11 — DB self-description layer for direct-SQL LLM consumption (COMMENT ON + query guide)

An LLM-consumption audit (run as `congress_ro`, the skill's own role) found the DB had **zero
in-database self-description** (0 table/column/function COMMENTs): an LLM that introspects the
schema sees bare column names and writes plausible-but-wrong SQL — `law_proc_dt` as 공포일 (wrong in
520/520 cases), `proc_result = '가결'` (0 rows; real values are 원안가결/수정가결), INNER-joining
`utterances → members` (silently drops 38.5% non-member speakers). Decision: add the gotcha/semantic
knowledge **where the LLM actually looks** — `COMMENT ON` on every trap-bearing table/column/function
(`db/migrations/011_schema_comments.sql`, applied to Neon and run by `db-migrate` on fresh installs) —
plus a consolidated, query-verified `docs/design/DB-QUERY-GUIDE.md` (table map, vocab, join recipes,
coverage caveats). The gotchas are intentionally duplicated across COMMENT / guide / CONTEXT.md because
each serves a different reader (the introspecting LLM, the skill author, the PM); the COMMENT is the
canonical inline surface and cannot drift out of the DB. This realizes the "DB must be self-sufficient"
consequence of the no-SDK decision (2026-06-10). No data changed — the gap was the consumption layer,
not the facts.

## 2026-06-11 — bill_final_outcomes stores PROM_LAW_NM, not a numeric law_id

Issue #86 planned a `law_id` column as the 법제처 bridge, but a live ALLBILL check shows the endpoint
returns no clean numeric 법령ID — only `PROM_LAW_NM` (the promulgated law name) and a `LINK_URL` that
merely points back to the likms bill page (`billDetail.do?billId=<BILL_ID>`). Decision: store
`prom_law_nm` (promulgated law name) instead of `law_id`; the law name is the actual key 법제처 (the
future statute SDK) is queried by, so the bridge intent is preserved while staying honest about what
the source provides. Reversible — a numeric 법령ID column can be added later if a source supplies one.

## 2026-06-10 — No 국회 SDK; the future skill queries Neon directly via SQL over a schema reference

The planned 국회 SDK (roadmap step 2) was a fixed query surface — brittle (one wrong or
missing method blocks the consumer) and an ongoing maintenance burden for a solo PM, while real
legislative-analysis questions are open-ended. Decision: drop the SDK; the future 입법전문가 스킬
connects to Neon and runs read-only SQL directly, guided by this DB's own schema/usage
documentation, because Claude is strong at SQL and the target skill is a human-in-the-loop
deliberative copilot (the user reviews every result, bounding ad-hoc-SQL risk). Consequences:
(1) a least-privilege **read-only DB role is now mandatory** — an LLM writing SQL must not hold
owner rights; (2) the DB must be **self-sufficient** because there is no SDK layer to paper over
gaps, which elevates the source-fact backfills below; (3) `docs/CONGRESS-SDK-CODEX-BRIEF.md` is
obsolete; (4) roadmap step 2 changes from "국회 SDK" to "DB reference + direct SQL". Reversible —
an SDK can wrap the same schema later if direct SQL proves insufficient.

## 2026-06-10 — BILL_NO is the stable cross-source key; BILL_ID can diverge per source

A 4-agent analysis + adversarial verification (transcript 2026-06-10) found that the 130 "missing"
대안 `bill_relations.alternative_bill_id`s compress to **15 distinct source ids, and 15/15 already
exist in `bills` under the same `BILL_NO` but a different `BILL_ID`** — e.g. relation target
`PRC_D2L5…` is, per likms/ALLBILL, `BILL_NO 2212725`, which `bills` stores as `PRC_V2S5…`. likms
and ALLBILL key by `BILL_NO`. Decision: keep `bills.bill_id` as PK, but treat `BILL_NO` as the
stable cross-source identity and add `bill_source_aliases(source, source_bill_id, bill_no,
canonical_bill_id)` to reconcile divergent source `BILL_ID`s to the canonical row. This
operationalizes (does not reverse) the 2026-06-06 "alternative_bill_id is a source key, not an FK"
decision, and still forbids synthetic `bills` rows.

## 2026-06-10 — Add bill_final_outcomes (ALLBILL 공포 bridge) keyed by BILL_NO, not columns on bills

`bills.law_proc_dt` is a 법사위 처리일, not 공포일 (570 present, all earlier than `proc_dt`;
promulgation absent entirely), and 720 distinct passed alternatives have it NULL — so "그 대안은
결국 통과·공포됐나?" dead-ends. A live ALLBILL check returns `PROM_DT` (공포일), `PROM_NO`
(공포번호), `GVRN_TRSF_DT` (정부이송일), `PPSL_DT` (제안일) keyed by `BILL_NO`. Decision: add a
separate `bill_final_outcomes(bill_no PK, plenary_dt, govt_transfer_dt, promulgation_dt, prom_no,
law_id, source)` ingested from ALLBILL rather than NULL-heavy columns on `bills` — keying by
`BILL_NO` reaches the BILL_ID-alias'd and missing alternatives that bills-columns cannot,
simultaneously backfills 대안 `propose_dt` via `PPSL_DT`, and provides the 국회-stage bridge key
(`law_id`) toward the later 법제처 layer (statute text stays out of scope).

## 2026-06-06 — bill_relations alternative id is a source key, not a required bills FK

During the #72 backfill, `selRefBillId` resolved all 3,715 target original bills, but 169 pointed to
ids not present in our `bills` table: 130 committee alternatives that likms detail pages expose but
our bill-list ingest missed, plus all 39 수정안 ids whose bill detail pages do not exist. Creating
synthetic `bills` rows would pollute the Bill entity, and enforcing an FK would discard authoritative
relationship facts, so `bill_relations.absorbed_bill_id` remains an FK while `alternative_bill_id`
is stored as the authoritative likms source key; it joins to `bills` when a row exists and can be
enriched later.

## 2026-06-06 — bill_relations source: scrape likms `selRefBillId`, not the OpenAPI

The 국회 OpenAPI exposes no 원안↔대안 relationship field — checked 발의법률안 (24 fields), ALLBILL
(full processing timeline soup-to-nuts, but no link), the dedicated 위원회안·대안 API
(`nxtkyptyaolzcbfwl`), and BPMBILLSUMMARY (returns policy text, not the absorbed-bill list). The
authoritative link lives only in 의안정보시스템 (likms) `billDetail.do` as a hidden
`<input id="selRefBillId">` pointing 원안→흡수 대안, in static HTML (sample 10/10 exact). So
`bill_relations` is populated by scraping selRefBillId (~100%, authoritative) rather than a
name+shared-committee-meeting heuristic (~80%, inferred) — precision matters more than effort for a
proposal-basis fact, and the scrape reuses the existing minutes-scraper pattern (no new
dependency). Scope: 대안반영폐기 (3,676) + 수정안반영폐기 (39), distinguished by `relation_type`.
Aside: ALLBILL carries 공포·본회의 dates absent from our `bills` table — future enrichment, out of
scope for this slice.

## 2026-06-06 — Track incumbency via a roster-derived boolean; never delete departed members

Departed legislators (사퇴/의원직 상실 등) are never removed — FK ON DELETE RESTRICT already
blocks deleting any member with votes/utterances, and member sync upserts rather than deletes.
The only missing piece was knowing who currently serves: add `members.is_incumbent` (BOOLEAN),
set TRUE for members present in the latest 인적사항 roster sync and FALSE otherwise, refreshed
automatically every sync (not hand-maintained) — consistent with the "derive point-in-time
facts from the source" pattern (cf. `votes.poly_nm_at_vote`). Chosen over a status enum +
end-date (no reliable source for reason/exact date → mostly NULL = over-design). Members who
depart after our sync window keep their last roster profile frozen; only the 20 pre-sync
departures stay profile-NULL (separate backlog). Floor-only vote scope reaffirmed (committee
votes are absent from the OpenAPI, not merely unimportant).

## 2026-06-05 — Foundation diagnosis: clean facts, not yet a proposal basis

A 9-agent diagnosis (transcript 2026-06-05) judged the DB a trustworthy SOURCE OF FACTS
but not yet a trustworthy BASIS FOR PROPOSALS — the threads a bill proposal must follow
dead-end. Two are now in scope to close in this repo (PRD #50-53): (1) bill-to-bill 대안
관계 + passed-대안 summary backfill, (2) speaker_role normalization + executive-branch
utterance attribution. Deferred to backlog: filling 20 profile-less member stubs, raising
상임위 meeting_bills coverage. Indicative fit scores: data/domain 52, architecture 42.

## 2026-06-05 — 국회 SDK stays a separate repo (reaffirmed after reconsidering in-place merge)

Considered renaming this repo to congress-sdk and growing the API/SDK in place. Rejected:
write-path (ingestion) and read-path (SDK) couple only through the Neon schema reached by
one DATABASE_URL, so the SDK needs the database, not this repo's code, scraping stack, or
batch lifecycle; their consumers and release cadences differ; and the downstream 법제처 SDK
+ harness (also separate repos) want 국회 SDK as an installable dependency. Reaffirms the
roadmap (CONTEXT 프로젝트 경계). Reversible (separate↔mono via history-preserving subtree
split/merge) if two-repo overhead proves too heavy for a solo PM.

## 2026-06-05 — Hybrid sequencing: stabilize foundation here, then SDK slices parallel to data fixes

Work order in THIS repo: M0 (doc-truth fixes, docs structure cleanup) → M1 (ADR-0008 schema
cleanup, search-ranking migration, Neon migration, hosting-continuity hardening) → open the
congress-sdk repo against the stabilized schema and build thin vertical slices, closing the
two M2 data threads (대안 관계, speaker_role) in parallel. Chosen over "all data first"
(delays end-to-end feedback) and "SDK first" (builds on knowingly-slanted data), per the
vertical-slice philosophy.

## 2026-06-05 — Accept the leaked (free) API key in git; remove legacy tree only for tidiness

The National Assembly OpenAPI key committed at .Seongjin/legacy_congress/.env is free and
trivially reissued, so the leak carries no billing risk; history is NOT scrubbed (PM
decision). The only residual is per-key rate-limit abuse, accepted. Removing
.Seongjin/legacy_congress/ (dead SQLite-era scripts + a 472KB binary) is therefore an
optional tidiness slice, not a security action. Executed in #58 after inline-preserving
the used endpoint inf_ids in `congress_db/core/endpoints.py`.

## 2026-06-05 — Consolidate per-file ADRs into this log; split docs into design/ vs ops/

Executed in slice #57. The previous per-file ADRs predated the single-decision-log decision
and were absorbed into this log with decision content preserved, then removed. docs/ now
splits into design/ (hand-edited: PRD, IA, ERD, DECISIONS, migration runbook) vs ops/
(code-generated reports: sanity, completeness, readiness, benchmarks, DOM validation);
generators write to docs/ops/ and that dir is gitignored.

## 2026-06-04 — Incremental meeting_bills skips linked bills and preserves existing links

After #46, incremental meetings cost was dominated by re-querying `VCONFBILLCONFLIST`
for already-linked bills. Incremental mode now fetches meeting-bill rows only for
missing/unlinked bills and bills on touched or forced meetings; it upserts new pairs
without deleting existing `meeting_bills`, leaving stale-link deletion to full
reconciliation/backfill. This trades rare stale-link cleanup latency for avoiding
false deletion when a skipped bill still owns an existing link.

## 2026-06-04 — Remove session_groups; minutes retrieval = utterance keyword + neighbor-reading

Following the agentic + ranked-keyword search decision, the Q&A semantic unit
(`session_groups`, 30,755 rows) is removed, not merely demoted. Rationale:
`utterances.speaker_mona_cd` already answers "who said what"; session_groups uniquely
added only questioner↔respondent pairing + Q&A block boundaries, both re-derivable on the
fly by an agentic harness; its accuracy was never measured (#50), coverage is uneven
(본회의·소위 none; 상임위 69%, 국정조사 65%, only 국정감사 99%); and it carried a
detection/eval subsystem plus an incremental regroup stage. Minutes content is untouched —
all 1.38M utterances remain; only the derived segmentation layer drops, and the detection
code stays in git if ever needed. Removal slice: #54; #50 closed as obsolete.

## 2026-06-04 — Search strategy: agentic + ranked keyword, defer vector embeddings

The search layer (roadmap steps 2-4) will use agentic keyword search — Claude issues
multiple domain-informed query variants, follows structural JOINs
(bill→votes→meetings→utterances), and iterates — over a keyword layer upgraded from
substring-only to relevance-ranked + snippets (Postgres-native `similarity()`/snippet, no
new infra). Vector/embedding semantic search is deferred, not adopted: this terminological,
citation-critical, low-QPS legislative domain lets Claude's own vocabulary + agentic
iteration recover most semantic recall, while embeddings carry ongoing maintenance (Korean
model hosting, weekly re-embedding of new utterances, model-version re-embeds, pgvector
storage/cost). Deferring is low-risk because pgvector is additive later (Neon supports it;
source text already stored) — no DB rebuild; revisit only if a measured recall failure
proves agentic+ranked-keyword insufficient. The `legislative-copilot` prototype already
validated keyword+agentic without vectors. DB implication: add relevance-ranking support
when the SDK slice begins.

## 2026-06-04 — Four-project roadmap: this repo is the 국회 DB only

The legislative-design harness needs three sources — 국회 (proposed/discussed/voted
bills, this repo), 법제처 (in-force statutes·decrees·official interpretations·precedents),
and WebSearch (social context) — so the work is split into four sequential, independent
projects: (1) 국회 data DB = this repo → (2) 국회 SDK → (3) 법제처 SDK → (4) harness skill,
keeping each project's scope bounded. Consequently statute/decree/interpretation/precedent
text is explicitly out of this repo (it belongs to the 법제처 SDK), and the prior
`legislative-copilot` prototype is reference-only and will be rebuilt. See CONTEXT.md
"프로젝트 경계 / 로드맵".

## 2026-06-04 — Incremental sync re-scans cheap lists, skips immutable items (drops the 30-day window)

The documented "source-specific cursor + 30-day overlap window" incremental design
(ADR-0006, PRD #37/#39, CONTEXT 증분 동기화) was never wired in: `incremental_plan.py` was
dead code and the live path full-refetched everything every run — re-pulling ~18k immutable
bill summaries and ~1,600 bills' vote rows, and re-running worker benchmarks. Decision:
incremental re-scans the cheap list endpoints in full each run (so late edits to old
records, e.g. a year-old bill's `proc_result` changing, are always caught) and upserts all,
but skips per-item fetches for items already present (bill summaries and vote rows are
immutable once set) and runs benchmarks only at first calibration; the date-window model is
dropped because legislative records are edited late and a 30-day window misses them.
Issue #46 removes the unused planner and verifies the behavior with public-interface tests
plus one real-source dry run. Supersedes the windowing aspect of ADR-0006.

## 2026-05-31 — Target Neon for the first hosted Postgres migration

The project currently needs hosted Postgres, not Auth/Storage/Realtime/Edge
platform features. The first remote target is Neon Launch, with a staging restore
before any production claim; Supabase stays as an alternative if product
requirements later need its broader platform surface.

## 2026-05-30 — Separate local data acceptance from strict clean replay proof

The accepted local database is ready for hosted Postgres human review because
run `103` finished with `success`, `0` dead letters, passing S1-S7 checks, and
`ready_for_human_review`. This does not claim a strict empty-DB one-shot replay
with the current code; that destructive rehearsal remains optional before
migration execution, not a blocker to migration planning.

## 2026-05-30 — Migration readiness runs after backfill completion

`migration_readiness` reads the latest backfill run, so running it as a stage
inside the same backfill sees that run as `running`. The official ingest command
now refreshes readiness after the backfill status is finalized.

## 2026-05-30 — Reuse completed backfill stages on rerun

Late-stage failures should not force expensive OpenAPI and meeting fetch stages
to run again. The official backfill now reuses healthy `members`, `bills`,
`votes`, and `meetings` summaries from previous failed backfill runs and records
the source run id in the new run summary.

## 2026-05-30 — Retry rate is a worker-selection signal

For external sources, eventual success with heavy retries is not stable enough
for the migration gate. OpenAPI and minutes benchmarks treat retry storms as a
worker rejection signal, not just as noisy logs.

## 2026-05-30 — Full session-group relink rebuilds the link index

The local full backfill relinks hundreds of thousands of utterances to
`session_groups`; maintaining the partial `session_group_id` index during that
write caused excessive IO. Large relinks temporarily drop and recreate that
index inside the transaction.

## 2026-05-29 — Single ingest entrypoint for PM and operator runs

PMs and operators should run one ingest command, not manually compose member, bill,
vote, meeting, utterance, and session-group stages. The command decides whether the
run is initial backfill or incremental sync, retries unresolved dead letters first,
avoids duplicate rows through upserts and scoped recalculation, and records the
decision path in `ingest_runs` so later sessions can audit what happened. Absorbed
from ADR-0009.

## 2026-05-29 — Keep core schema search-oriented

Congress-DB is the foundation for future search APIs/SDKs, not a full archive of
every upstream field. Source links, source-tracking fields, and `agenda_items` are
kept out of the core schema before hosted Postgres migration; official meeting
agenda text may be used transiently to derive `meeting_bills`, while policy topics
and positions will be modeled later as a separate evidence-backed semantic layer.
Absorbed from ADR-0008.

## 2026-05-29 — Web minutes list is the canonical meeting universe

The public OpenAPI meeting endpoints and the `record.assembly.go.kr/assembly/mnts/total/22.do`
web listing do not expose the same 22대 minutes universe, while utterances are parsed
only from HTML viewer pages. The web listing is the canonical meeting universe;
OpenAPI meeting endpoints only enrich metadata and law-bill links by matching
`mnts_id`, and PDF/HWP stay out of utterance extraction. Absorbed from ADR-0007.

## 2026-05-27 — Backfill and incremental ingest share modules

Initial 22대 backfill and later incremental sync use the same ingest modules; only
execution mode differs. The original source-specific cursor + 30-day overlap window
was later superseded on 2026-06-04: incremental now re-scans cheap list endpoints in
full, skips immutable per-item fetches, and leaves cursors as audit markers. Absorbed
from ADR-0006 and updated with its supersession note.

## 2026-05-27 — Use pg_trgm for first Korean keyword search

For the first hosted-Postgres-bound search slice, Korean keyword search uses `pg_trgm`
GIN indexes on bill names, bill summaries, and utterance content. PGroonga remains a
stronger multilingual option, but adopting it now would change the local Postgres
runtime before the project proves substring keyword search is insufficient. Absorbed
from ADR-0005.

## 2026-05-27 — Validate minutes HTML before accepting utterances

The meeting-minutes HTML endpoint can transiently return a different meeting's DOM
under parallel scraping, so utterance ingest validates the parsed meeting date
against `meetings.conf_date` before accepting a response. Scraping remains parallel,
but the default worker count is capped at 5 until a later full-load run proves higher
concurrency preserves metadata correctness, not just HTTP success. Absorbed from
ADR-0004.

## 2026-05-27 — Calibrate parallel ingest before full load

The initial 10% load is a calibration phase, not the product goal: it measures worker
counts for unknown National Assembly OpenAPI and meeting HTML limits before attempting
100% collection. For meeting metadata the calibration target is about 500 meetings
across all five source APIs, and per-bill enrichment (`VCONFBILLCONFLIST`) uses the
measured worker policy so the later full load can be fast without blindly increasing
concurrency. Absorbed from ADR-0003.

## 2026-05-27 — Normalize lead proposers and member stubs

The bill API can put multiple lead proposers in `RST_MONA_CD`, and it can reference
MONA_CD values not returned by the member-profile API. Dropping those references or
removing FKs would weaken the core "JOIN by member ID" value, so lead proposers are
normalized into `bill_lead_proposers`, and missing members are preserved as name-only
`members` stubs. `bills.rst_mona_cd` was kept then as a single-lead convenience FK,
but the 2026-06-13 cleanup removes it after `bill_lead_proposers` became the sole
authoritative lead proposer interface. Absorbed from ADR-0002.

## 2026-05-26 — api_catalog covers only pipeline OpenAPI endpoints

`api_catalog` verifies and documents only the PRD-confirmed OpenAPI endpoints used
by the pipeline, with `used_in_pipeline=TRUE`; unused OpenAPI metadata is not
maintained in this repo after the #58 legacy cleanup. This avoided low-ROI
verification of 263 unused APIs while preserving an easy extension path: find and
add the needed endpoint row when the pipeline actually uses it. Later
`ncocpgfiaoituanbr` was added through that path for vote candidate BILL_ID
discovery. Absorbed from ADR-0001 and updated after #58.
