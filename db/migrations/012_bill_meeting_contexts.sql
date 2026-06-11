-- 012_bill_meeting_contexts.sql — 회의 fanout evidence 가드레일 (#91)
--
-- 목적: meeting_bills는 회의 단위 연결이라 한 회의에 수십~수백 법안이 걸린다(평균 32, p90 75, max 756).
-- "같은 회의에서 다뤄짐"을 특정 법안의 발언 증거로 단정하면 소비자(입법 스킬)가 과잉주장한다.
-- 이 뷰는 회의의 fanout(linked_bill_count)과 회의 단위 발언 통계를 (법안×회의) grain으로 노출하고
-- evidence_scope='meeting_level'로 "발언이 이 법안에 직접 귀속되지 않음"을 *그 자리에서* 알린다.
-- 증거강도 버킷 라벨(specific/crowded)은 일부러 만들지 않는다 — 분포가 연속이라 ≤3/31+ 경계가
-- 임의값이고, raw count를 보면 소비자가 스스로 판단한다(DECISIONS 2026-06-11 소비 적합성 원칙).
-- 새 적재 없음(meeting_bills+meetings+utterances 파생). 멱등(CREATE OR REPLACE).
--
-- 성능: 회의 단위 집계를 상관 서브쿼리로 둔다. 소비자는 bill_id(또는 meeting_id)로 타깃 조회하므로
-- idx_mb_bill·idx_utterances_meeting으로 빠르다. 사전집계 CTE는 매 쿼리 1.38M 발언 전체를 집계하게
-- 만들어 타깃 조회를 느리게 하므로 피한다. 전체 스캔(SELECT * 무필터)은 의도된 사용이 아니다.

CREATE OR REPLACE VIEW bill_meeting_contexts AS
SELECT
    mb.bill_id,
    mb.meeting_id,
    m.meeting_type,
    m.comm_name,
    m.conf_date,
    (SELECT count(*) FROM meeting_bills mb2 WHERE mb2.meeting_id = mb.meeting_id)
        AS linked_bill_count,
    (SELECT count(*) FROM utterances u WHERE u.meeting_id = mb.meeting_id)
        AS utterance_count,
    (
        SELECT coalesce(jsonb_object_agg(role, cnt), '{}'::jsonb)
        FROM (
            SELECT coalesce(speaker_role, '기타') AS role, count(*) AS cnt
            FROM utterances u
            WHERE u.meeting_id = mb.meeting_id
            GROUP BY coalesce(speaker_role, '기타')
        ) r
    ) AS utterances_by_role,
    'meeting_level'::text AS evidence_scope
FROM meeting_bills mb
JOIN meetings m ON m.mnts_id = mb.meeting_id;

COMMENT ON VIEW bill_meeting_contexts IS
  '법안×회의 evidence 컨텍스트(파생 뷰, 새 적재 없음). linked_bill_count=그 회의에 연결된 법안 수(fanout; 평균 32, p90 75, max 756) — 클수록 이 회의 발언을 해당 법안의 직접 증거로 보기 어렵다. utterance_count·utterances_by_role는 회의 단위 집계(evidence_scope=meeting_level): 발언↔특정 법안 직접 귀속은 원천이 주지 않는다. 증거강도 버킷 라벨은 일부러 두지 않음 — raw count로 소비자가 판단(DECISIONS 2026-06-11). meeting_bills 커버리지가 부분적이라 결과가 비어도 미논의를 뜻하지 않음.';
