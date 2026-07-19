-- 034_data_freshness_view.sql — 신선도 소비 표면 (WI4, F4)
--
-- 결정(DECISIONS 2026-07-19): 스테이지별 신선도가 한 달씩 벌어질 수 있음이 실증됐다(공포 이력은
-- 2026-06-10, bills는 07-15). fetched_at COMMENT가 "운영 감사 메타"라고 소비자를 밀어내고 votes엔
-- fetched_at 자체가 없어, 소비자가 "이 데이터가 며칠 기준인가"를 확인할 단일 표면이 없었다. 도메인별
-- 1행으로 last_ingest_at(수집 시각)·latest_fact_date(최신 사실 날짜)를 노출하는 뷰를 만든다. 뷰는 owner
-- 권한으로 실행되므로 REVOKE된 bill_relations.fetched_at도 노출 가능(bill_lineage 캡슐화 전례와 동일).

CREATE OR REPLACE VIEW data_freshness AS
SELECT 'bills'::text               AS domain,
       max(fetched_at)             AS last_ingest_at,
       max(propose_dt)::date       AS latest_fact_date
FROM bills
UNION ALL
SELECT 'members',
       max(fetched_at),
       NULL::date
FROM members
UNION ALL
SELECT 'votes',
       NULL::timestamptz,          -- votes엔 fetched_at이 없다(수집 시각 미보유)
       max(vote_date_kst)::date    -- 최신 표결일(KST 달력일)
FROM votes
UNION ALL
SELECT 'bill_final_outcomes',
       max(fetched_at),
       max(promulgation_dt)::date  -- 최신 공포일
FROM bill_final_outcomes
UNION ALL
SELECT 'bill_relations',
       max(fetched_at),
       NULL::date
FROM bill_relations;

COMMENT ON VIEW data_freshness IS
  '스테이지(도메인)별 신선도 1행: last_ingest_at=그 도메인을 마지막으로 수집·갱신한 시각(votes는 fetched_at 미보유라 NULL), latest_fact_date=도메인 최신 사실 날짜(bills=최신 발의일, votes=최신 표결일, outcomes=최신 공포일; members·relations은 사실 날짜 없음 NULL). **미공포·계류·불참·최신 지형을 단정하기 전 이 뷰로 신선도를 확인하고, 산출물에 기준일을 병기하라.** last_ingest_at이 오래됐다면 "공포 행 없음"은 미공포가 아니라 미수집일 수 있다(스테이지마다 수집 시점이 다를 수 있음 — 예: 공포 이력이 bills보다 뒤처지면 최근 가결분의 공포가 아직 안 붙었을 수 있다).';

-- bills·bill_final_outcomes의 fetched_at COMMENT를 "운영 감사 메타"에서 "신선도 판단엔 쓴다"로 교체.
COMMENT ON COLUMN bills.fetched_at IS
  '법안 row를 마지막으로 수집·갱신한 시각. 행 단위 분석 fact는 아니지만 신선도 판단에는 쓴다 — 전체 신선도는 data_freshness 뷰를 볼 것.';
COMMENT ON COLUMN bill_final_outcomes.fetched_at IS
  'ALLBILL outcome row를 마지막으로 수집·갱신한 시각. 행 단위 분석 fact는 아니지만 신선도 판단에는 쓴다 — 전체 신선도는 data_freshness 뷰를 볼 것.';

-- 소비자 노출: 뷰만 GRANT(underlying bill_relations 등은 여전히 REVOKE 유지 — 뷰가 owner 권한으로 캡슐화).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'congress_ro') THEN
        GRANT SELECT ON data_freshness TO congress_ro;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anonymous')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        GRANT SELECT ON data_freshness TO anonymous, authenticated;
    END IF;
END $$;
