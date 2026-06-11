-- 013_promulgation_completeness_comments.sql — 공포 완전성 inform 레이어 (#90)
--
-- 결정(AskUserQuestion 2026-06-12, DECISIONS 2026-06-11 소비 적합성 원칙): 공포 완전성은
-- *판정을 materialize하지 않고 inform한다*. "법률안인가?"는 bill_name 패턴이라 소비자(입법
-- 스킬 속 Claude)가 도출 가능한 어휘 판정이므로, bill_kind 분류기·뷰·컬럼을 만들지 않고
-- COMMENT + DB-QUERY-GUIDE 레시피로 알린다. 4-way status(promulgated_with_name/no_name/
-- not_promulgable/pending)도 소비자가 prom 필드 + bill_name 패턴으로 그 자리에서 합성한다.
--
-- 실데이터 근거(congress_ro, 2026-06-12): bills 18,361 = 법률안 18,192(bill_name ~ '법(률)?안',
-- 비-법률과 오탐 0건) + 비-법률 의안 169(결의안·동의안·승인안·감사요구안·규칙안·각종 '~의 건'·
-- 기금운용계획변경안·국정조사계획서 등 — 통과해도 not_promulgable). prom_law_nm 갭 66건은 전부 법률안.
-- 멱등(COMMENT ... IS는 덮어씀).

COMMENT ON COLUMN bills.bill_name IS
  '의안 제목. bills에는 법률안(약 18,192건) 외 비-법률 의안(결의안·동의안·승인안·감사요구안·규칙안·각종 ''~의 건''·기금운용계획변경안·국정조사계획서 등 약 169건)이 섞여 있고, 이들은 통과해도 공포 대상이 아님(not_promulgable). 법률안만 거르려면 bill_name ~ ''법(률)?안''(비-법률과 오탐 0 검증) — 비-법률 종류를 열거하면 미달함. 따라서 "통과(proc_result 가결)했는데 bill_final_outcomes에 공포 없음"은 *법률안일 때만* [1] 갭(pending/결측), 비-법률이면 정상이다. 상세 레시피: DB-QUERY-GUIDE Q2.';

COMMENT ON COLUMN bill_final_outcomes.prom_law_nm IS
  '공포 법률명. ALLBILL은 숫자 법령ID를 주지 않음(현행법 본문은 법제처 단계로 이어지는 bridge). 공포일(promulgation_dt)은 있으나 이 값이 NULL인 66건은 전부 법률안의 실제 [1] 품질 갭(원천 미제공) — 이름에서 유도해 backfill하지 말 것(source가 줄 때만 채움).';
