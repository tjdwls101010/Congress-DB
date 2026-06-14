-- 024_drop_members_elect_gbn_nm.sql — 잉여 선출구분 컬럼 제거 (#126)
--
-- 결정(DECISIONS 2026-06-14): members.elect_gbn_nm은 orig_nm의 순수 함수다 — 라이브 검증
-- (congress_ro, 2026-06-14): 320/320 행에서 CASE(orig_nm='비례대표'→비례대표, NULL→NULL, else→지역구)와
-- 완전 일치(어긋남 0; 지역구 254·비례대표 46·NULL 20). members는 소비자 표면에 남으므로 도출가능 컬럼은
-- introspection 노이즈다(relation_type와 달리 REVOKE 대상 아님, ETL 내부 읽기 없음 → 진짜 잉여).
-- DROP하고 orig_nm COMMENT에 도출 규칙을 남긴다. 멱등.

ALTER TABLE members DROP COLUMN IF EXISTS elect_gbn_nm;

COMMENT ON COLUMN members.orig_nm IS
  '현재 선거구명. 선출구분(지역구/비례대표)은 여기서 도출한다: orig_nm=''비례대표''면 비례대표, NULL이면 미상(명부-결손 stub 의원 ~20명), 그 외는 지역구. (별도 elect_gbn_nm 컬럼은 잉여로 제거됨, #126.)';
