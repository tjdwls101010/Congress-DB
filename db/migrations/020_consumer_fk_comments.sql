-- 020_consumer_fk_comments.sql — consumer-visible relationship/comment legibility
--
-- Adds a real FK for the ALLBILL outcome bridge and fills high-risk comments
-- that the direct-SQL skill sees through introspection.

DO $$
DECLARE
    orphan_count integer;
BEGIN
    SELECT count(*) INTO orphan_count
    FROM bill_final_outcomes o
    LEFT JOIN bills b ON b.bill_no = o.bill_no
    WHERE b.bill_no IS NULL;

    IF orphan_count > 0 THEN
        RAISE EXCEPTION
            'cannot add bill_final_outcomes.bill_no FK: orphan rows exist: %',
            orphan_count;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.bill_final_outcomes'::regclass
          AND conname = 'bill_final_outcomes_bill_no_fkey'
    ) THEN
        ALTER TABLE bill_final_outcomes
            ADD CONSTRAINT bill_final_outcomes_bill_no_fkey
            FOREIGN KEY (bill_no) REFERENCES bills (bill_no) ON DELETE RESTRICT;
    END IF;
END $$;

COMMENT ON COLUMN bill_final_outcomes.bill_no IS
  'FK to bills.bill_no. ALLBILL outcome rows join by stable 7-digit bill_no, not source-specific bill_id.';
COMMENT ON COLUMN bill_final_outcomes.govt_transfer_dt IS
  '정부이송일(원천 GVRN_TRSF_DT). 본회의 의결 이후 공포 전 단계 날짜.';
COMMENT ON COLUMN bill_final_outcomes.prom_no IS
  '공포번호(PROM_NO). 법제처 현행법 조회로 이어질 때 prom_law_nm과 함께 bridge key 후보.';
COMMENT ON COLUMN bill_final_outcomes.fetched_at IS
  'ALLBILL outcome row를 마지막으로 수집·갱신한 시각. 소비 분석 fact가 아니라 운영 감사 메타데이터.';

COMMENT ON COLUMN bill_source_aliases.source IS
  'source_bill_id의 출처 이름. 같은 BILL_ID 문자열이라도 source별 의미가 다를 수 있어 PK 일부로 보존.';
COMMENT ON COLUMN bill_source_aliases.source_bill_id IS
  'source가 제공한 원본 BILL_ID. bill_relations.alternative_bill_id 같은 source key를 canonical bills row로 해소할 때 쓴다.';
COMMENT ON COLUMN bill_source_aliases.bill_no IS
  'source detail에서 확인한 안정 의안번호. canonical_bill_id 해소의 중간 키.';
COMMENT ON COLUMN bill_source_aliases.canonical_bill_id IS
  '해소된 public.bills.bill_id. NULL이면 source key를 현재 bills row로 연결하지 못한 accepted gap.';
COMMENT ON COLUMN bill_source_aliases.fetched_at IS
  'source alias 해소를 마지막으로 시도·갱신한 시각. 소비 분석 fact가 아니라 운영 감사 메타데이터.';

COMMENT ON COLUMN bills.committee IS
  '소관 위원회명 원문. committee_id의 표시명 역할도 하므로 committee dimension 없이 삭제하면 이름 정보가 사라진다.';
COMMENT ON COLUMN bills.committee_id IS
  '소관 위원회 코드. 법안 쪽 위원회 identity key이며, meetings.comm_name과 직접 FK는 아님.';
COMMENT ON COLUMN bills.fetched_at IS
  '법안 row를 마지막으로 수집·갱신한 시각. 소비 분석 fact가 아니라 운영 감사 메타데이터.';

COMMENT ON COLUMN votes.bill_id IS
  'PK 일부, FK to bills.bill_id. 표결 row grain은 one bill × one member.';
COMMENT ON COLUMN votes.mona_cd IS
  'PK 일부, FK to members.mona_cd. 표결 당시 정당은 poly_nm_at_vote를 사용할 것.';

COMMENT ON COLUMN utterances.id IS
  '발언 surrogate id. search_utterances()가 utterance_id로 반환하는 현재 검색 결과 identity.';
COMMENT ON COLUMN utterances.meeting_id IS
  'FK to meetings.mnts_id. 발언 stream과 주변 문맥 복원은 meeting_id + sequence로 한다.';
COMMENT ON COLUMN utterances.sequence IS
  '회의 안 발언 순서. 같은 meeting_id 안에서만 의미 있으며 UNIQUE(meeting_id, sequence)로 보존된다.';
COMMENT ON COLUMN utterances.speaker_title IS
  '회의록 원문 화자 직함. 정부측/증인/참고인 세부 구분은 speaker_role만으로 부족할 수 있어 이 원문을 함께 본다.';
COMMENT ON COLUMN utterances.content IS
  '발언 본문. search_utterances()와 content trigram index의 검색 대상.';

COMMENT ON COLUMN bill_meeting_contexts.bill_id IS
  '법안 id. 이 뷰의 grain은 bill_id × meeting_id.';
COMMENT ON COLUMN bill_meeting_contexts.meeting_id IS
  '회의 id. 회의 단위 연결이라 발언이 특정 법안에 직접 귀속된다는 뜻은 아님.';
COMMENT ON COLUMN bill_meeting_contexts.meeting_type IS
  '회의 종류. bills 처리 단계가 아니라 해당 회의록의 meeting_type.';
COMMENT ON COLUMN bill_meeting_contexts.comm_name IS
  '회의 소관 위원회명. bills.committee_id와 직접 FK가 아니며 공백 정규화 JOIN이 필요할 수 있음.';
COMMENT ON COLUMN bill_meeting_contexts.conf_date IS
  '회의일.';
COMMENT ON COLUMN bill_meeting_contexts.linked_bill_count IS
  '같은 회의에 연결된 법안 수. 클수록 회의 발언을 이 법안의 직접 증거로 단정하기 어렵다.';
COMMENT ON COLUMN bill_meeting_contexts.utterance_count IS
  '해당 회의 전체 발언 수. 특정 법안 발언 수가 아니라 meeting-level count.';
COMMENT ON COLUMN bill_meeting_contexts.utterances_by_role IS
  '해당 회의 전체 발언의 speaker_role별 count JSON. 특정 법안에 직접 귀속된 count가 아니다.';
COMMENT ON COLUMN bill_meeting_contexts.evidence_scope IS
  '항상 meeting_level. 원천이 발언과 특정 법안의 직접 귀속을 제공하지 않는다는 경고.';
