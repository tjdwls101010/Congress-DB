-- 038_prom_law_nm_norm_generated.sql — 공포 법률명 정규화 생성컬럼 (WI4b·C3)
--
-- 결정(DECISIONS 2026-07-19): 법제처 등 외부 법령명과 이름 매칭할 때 소비자가 매번 재조립하던
-- 정규화(중점 코드포인트 통일 + 공백 제거) 레시피를 생성컬럼으로 승격한다. translate/replace는
-- IMMUTABLE이라 STORED 허용, drift 불가, 규칙 투명, 저작 판단 없음(§3 razor). NULL은 NULL 유지.
--
-- 정규화 규칙: U+318D(ㆍ, chr(12685)) → U+00B7(·, chr(183)) 통일 후 공백 제거. 공포 법률명이
-- 가운뎃점을 U+00B7과 U+318D로 혼재 표기해, 공백만 지워선 코드포인트가 달라 exact-match가 깨지던
-- 함정을 엔진에서 제거한다. **1차 bridge 키는 여전히 prom_no다** — 이 컬럼은 이름으로 매칭해야 할
-- 때의 보조 키이며, 상대측(법제처) 이름에도 같은 정규화를 적용해야 맞는다.

ALTER TABLE bill_final_outcomes
    ADD COLUMN IF NOT EXISTS prom_law_nm_norm TEXT
    GENERATED ALWAYS AS (
        replace(translate(prom_law_nm, chr(12685), chr(183)), ' ', '')
    ) STORED;

COMMENT ON COLUMN bill_final_outcomes.prom_law_nm_norm IS
  '공포 법률명(prom_law_nm)을 정규화한 생성컬럼(STORED, IMMUTABLE): 가운뎃점 U+318D(ㆍ)→U+00B7(·) 통일 후 공백 제거(NULL은 NULL 유지). 법제처 등 외부 법령명과 이름으로 매칭할 때 이 컬럼을 쓰되, **상대측 이름에도 같은 정규화(translate+replace)를 적용**하라 — 한쪽만 정규화하면 코드포인트·공백 차이로 조용히 0행이 된다. **1차 bridge 키는 여전히 prom_no**(공포 100% 채움)이고, 이 컬럼은 이름 매칭이 불가피할 때의 보조 키다.';
