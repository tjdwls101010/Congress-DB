-- 015_cleanup_consumer_schema.sql — 소비자 스키마 정리 (16-테이블 심층 설계 감사 2026-06-12)
--
-- 결정(DECISIONS 2026-06-12): 소비자(입법전문가 스킬)가 introspect하는 스키마 표면 자체가 소비자
-- 컨텍스트라, 중복·도출가능·죽은·직무무관·이름거짓 필드는 추론을 흐리는 노이즈다(skill-creator
-- 'irrelevant text degrades the model' 원칙을 DB에 적용). 16-테이블 감사 + 반증 검증으로 확정한,
-- 소비자/회귀/뷰가 *읽지 않는*(ETL 전용) 것만 제거 — 전부 다른 컬럼·테이블·title에서 재도출 가능.
-- 반증으로 살아남은 것(proposer 자유텍스트·committee·cmt_proc_result·rst_mona_cd·canonical_bill_id·
-- plenary_dt·speaker_role·order_no·relation_type 등)은 유지하고 COMMENT로 명료화. 멱등.

-- ============================ 1. DROP — 중복/죽은/직무무관/이름거짓 ============================
-- bills: 발의자 중복문자열(=join string_agg과 정확 일치) + 죽은 _cd
ALTER TABLE bills
    DROP COLUMN IF EXISTS rst_proposer,        -- = string_agg(bill_lead_proposers→hg_nm) 17,333/17,333
    DROP COLUMN IF EXISTS publ_proposer,       -- = string_agg(bill_coproposers→hg_nm) 17,311/17,311
    DROP COLUMN IF EXISTS law_proc_result_cd;  -- 96.9% NULL·2값(proc_result에 이미 있음)·미사용

-- members: 연락처 directory + 도출가능 선수 + 이름거짓 cmits + HTML 약력 blob
ALTER TABLE members
    DROP COLUMN IF EXISTS tel_no,
    DROP COLUMN IF EXISTS e_mail,
    DROP COLUMN IF EXISTS homepage,
    DROP COLUMN IF EXISTS assem_addr,
    DROP COLUMN IF EXISTS reele_gbn_nm,        -- = units 콤마토큰 수(초선/N선) 300/300
    DROP COLUMN IF EXISTS cmits,               -- 84.7% NULL·특위 7종만·"현재 위원회"라 거짓(membership은 범위 밖)
    DROP COLUMN IF EXISTS mem_title;           -- raw-HTML 약력 blob, units/poly_nm/cmits를 산문으로 중복

-- votes: bill-level 상수를 의원행마다 복제한 도출가능/불투명 코드
ALTER TABLE votes
    DROP COLUMN IF EXISTS session_cd,          -- = max(meetings.session_no) via meeting_bills 1,595/1,595
    DROP COLUMN IF EXISTS currents_cd;         -- 불투명 '원천 코드'(1-18), 아무것과도 무상관·미사용

-- meetings: title에서 파생되는 웹목록 렌더링 잔재 (소비자 0 read)
ALTER TABLE meetings
    DROP COLUMN IF EXISTS is_appendix,         -- 100% = title LIKE '%(부록)%'
    DROP COLUMN IF EXISTS degree,              -- title에서 파싱, 절반이 '개회식' sentinel
    DROP COLUMN IF EXISTS is_temporary;        -- 웹목록 '[임시]' 배지(임시국회 아님)

-- 단일 상수 provenance 컬럼 (테이블 COMMENT가 이미 출처 기록)
ALTER TABLE bill_relations      DROP COLUMN IF EXISTS source;  -- 전행 'likms_selrefbillid'
ALTER TABLE bill_final_outcomes DROP COLUMN IF EXISTS source;  -- 전행 'allbill'

-- ============================ 2. RENAME — 이름이 내용을 속이는 _cd ============================
-- 라벨(대안반영폐기·수정가결·회송…)을 담는데 _cd 접미사가 '숫자코드/룩업'을 기대하게 만듦.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='bills' AND column_name='cmt_proc_result_cd') THEN
        ALTER TABLE bills RENAME COLUMN cmt_proc_result_cd TO cmt_proc_result;
    END IF;
END $$;

-- ============================ 3. REVOKE — ops를 소비자 introspection에서 숨김 ============================
-- 물리 유지(ETL/운영용). information_schema가 권한 필터링하므로 소비자 테이블 목록에서 사라진다.
-- congress_ro는 Neon 전용 role이라 로컬 docker엔 없음 → role-guard.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='congress_ro') THEN
        REVOKE SELECT ON ingest_runs, ingest_cursors, dead_letters FROM congress_ro;
    END IF;
END $$;

-- ============================ 4. COMMENT — legibility/함정 (소비자가 introspect로 읽음) ============================
COMMENT ON COLUMN members.hg_nm IS
  '표시용 한글 이름. 동명이인 존재(예: 박지원 2명, mona_cd 다름·표결수 0 vs 1595) → 식별·join은 반드시 mona_cd로. hg_nm으로 join 금지.';
COMMENT ON COLUMN members.units IS
  '역대 당선 대수 콤마구분 원문(예: ''제20대, 제21대, 제22대''). 22대 이전 이력의 유일 출처. 선수(초선/재선/N선)는 콤마 토큰 수로 도출(별도 컬럼 두지 않음).';

COMMENT ON COLUMN bills.rst_mona_cd IS
  '단일 대표발의 편의 FK. 다중 대표발의(191건)면 NULL이라 불완전 — 정확·완전·다중 대표발의는 bill_lead_proposers를 쓸 것(authoritative).';
COMMENT ON COLUMN bills.cmt_proc_result IS
  '소관위 처리결과(대안반영폐기·수정가결·회송·철회·심사미료 등 라벨, 코드 아님). 본회의 proc_result와 다른 단계 — 소관위에서 폐기돼 본회의 미상정인 728건은 이 값만 있고 proc_result는 NULL.';
COMMENT ON COLUMN bills.proposer IS
  '제안자 원문 텍스트(예: ''홍길동의원 등 17인''). 정확한 대표/공동 발의자는 bill_lead_proposers·bill_coproposers join이 authoritative — 이 컬럼은 raw 문구로, 대규모 공동발의(''외 N인'')의 총 서명자 수처럼 join 테이블이 복원 못 하는 값만 보존한다.';

COMMENT ON TABLE bill_lead_proposers IS
  '대표발의 N:M(bill_id×mona_cd). bills.rst_mona_cd가 못 담는 다중 대표발의(191건, 최대 3인)의 authoritative 소스. 주의: 대표발의자 ~20명은 22대 명부에 없어 members에 이름만(poly_nm·units NULL) — 정당/선수 필터 시 조용히 누락될 수 있음.';
COMMENT ON COLUMN bill_lead_proposers.order_no IS
  '원천 RST_MONA_CD 콤마 나열(서명) 순서(1부터). 다중 대표발의 시 문서상 서명 순서 보존 — 서열/선임 아님. 단일 대표발의는 항상 1.';
COMMENT ON TABLE bill_coproposers IS
  '공동발의 N:M(bill_id×mona_cd, 206k). co와 lead는 같은 법안에서 겹치지 않음 → 총 발의자 = 두 테이블 합집합(중복 없음). 1건당 보통 8~190명(중앙값 ~10), 모든 공동법안은 대표법안 부분집합(orphan 없음).';
COMMENT ON COLUMN bill_coproposers.order_no IS
  '원천 나열(서명) 순서 — 서열·역할·선임 아님. position 1 ≠ 대표발의자.';

COMMENT ON COLUMN votes.vote_date IS
  '본회의 표결 일시. 의미상 bill-단위(같은 법안 모든 의원행이 같은 표결 순간 공유). 행간 ±1~2초는 정렬용 인공 jitter니 초단위 비교 금지, 일자 비교만 신뢰.';
COMMENT ON COLUMN votes.result_vote_mod IS
  '표결값: 찬성·반대·기권·불참. votes는 본회의 표결까지 간 법안만(1,595/18,361) 담고 거의 전부 가결(1593/1595)이라 반대 1.5%·기권 1.2%로 극소 — 부결·계류 법안의 반대표는 없음. 찬반 대립 분석 시 이 생존편향을 밝힐 것.';
COMMENT ON TABLE votes IS
  '본회의 표결, 의원 1명당 1행. 행이 있으면 본회의까지 간 의안; 없으면 미상정이거나 원천 미수집(votes만으론 구분 불가 — bills.proc_result로 교차확인). 위원회 단계 표결은 원천이 안 줘 데이터에 없음. 표결된 법안 수 = count(DISTINCT bill_id).';

COMMENT ON COLUMN meetings.session_no IS
  '회기(session) 번호. title에서 도출 불가(0/2105 substring). 회차(degree)와 다름.';

COMMENT ON COLUMN utterances.speaker_name IS
  'mona_cd 있는 행은 members.hg_nm와 동일(847,511/847,511) — 의원 canonical 필드는 members join. speaker_name은 mona_cd가 NULL인 비-의원(장관·증인·참고인·기관장) 38.5% 행의 유일 식별자.';

COMMENT ON COLUMN bill_relations.relation_type IS
  '''대안반영''|''수정안반영''. absorbed bill의 proc_result에서 1:1 도출. 해소 가능성 힌트: 대안반영=100% 해소, 수정안반영=100% gap(39건 unresolved는 전부 이쪽).';
COMMENT ON COLUMN bill_final_outcomes.plenary_dt IS
  'FINAL 본회의 의결일(원천 RGS_RSLN_DT). 재의결(거부권 후 재의결)이면 bills.proc_dt보다 늦을 수 있음(26건 검증, 예: 방송법 2024-12-26→2025-04-17) → plenary_dt=proc_dt로 가정 금지.';
