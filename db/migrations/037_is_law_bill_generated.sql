-- 037_is_law_bill_generated.sql — 법률안 여부 생성컬럼 (WI4b·C2)
--
-- 결정(DECISIONS 2026-07-19): "가결-미공포를 계류/거부권 후보로 세기 전 법률안만 좁혀라"는 규칙은
-- 기계적(이름 정규식)이고 소비자가 매번 재조립하던 함정이다. IMMUTABLE 엔진 계산이라 base와 drift가
-- 불가능하고 규칙이 투명하며 저작 판단이 없으므로(§3 razor) 생성컬럼으로 승격한다. 과거 bill_kind
-- 유보(M3)의 최소·안전 버전으로 supersede한다 — 다분류(결의안/감사요구안 등 세부 종류)는 여전히
-- 유보하고, 여기선 "법률안 vs 비-법률"의 이분만 엔진에 박는다.
--
-- textregexeq(~)는 IMMUTABLE이라 STORED 생성컬럼에 허용된다. 적재 INSERT는 전부 명시적 컬럼 목록이라
-- 생성컬럼을 대상으로 삼지 않는다(vote_date_kst 전례와 동일). 기존 테이블 단위 SELECT GRANT에 자동 포함.

ALTER TABLE bills
    ADD COLUMN IF NOT EXISTS is_law_bill BOOLEAN
    GENERATED ALWAYS AS (bill_name ~ '법(률)?안') STORED;

COMMENT ON COLUMN bills.is_law_bill IS
  '법률안(공포 대상) 여부 — 원천에 의안종류 필드가 없어 bill_name에서 파생한 생성컬럼(STORED, IMMUTABLE 엔진 계산이라 base와 drift 불가). 규칙: bill_name ~ ''법(률)?안''(특별법안·특별조치법안도 매칭). 비정형 명명은 오분류 가능하나 규칙이 투명해 검증 가능하다. **용도:** "가결인데 공포 outcome 없음"을 계류·거부권 후보로 세기 전 이 컬럼(is_law_bill = true)으로 법률안만 좁혀라 — 결의안·감사요구안·수사요구안 등 비-법률 가결 의안은 공포 비대상이 정상이라 안 좁히면 계류가 과대 집계된다. **분리-보고:** 가결 건수와 공포 건수는 다른 모집단이다(가결 = 법률안+비-법률, 공포 = 법률안 일부) — 하나로 뭉뚱그리지 말고 나눠 보고할 것.';
