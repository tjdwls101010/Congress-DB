-- 021_normalize_committees.sql — bill-side committee dimension
--
-- Normalizes bills.committee_id + bills.committee into committees before
-- removing the duplicated bills.committee display column.

CREATE TABLE IF NOT EXISTS committees (
    committee_id          TEXT PRIMARY KEY,
    committee_name        TEXT NOT NULL UNIQUE
);

DO $$
DECLARE
    partial_pair_count integer;
    id_conflict_count integer;
    name_conflict_count integer;
    existing_mismatch_count integer;
    orphan_committee_id_count integer;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'bills'
          AND column_name = 'committee'
    ) THEN
        SELECT count(*) INTO partial_pair_count
        FROM bills
        WHERE (committee_id IS NULL) <> (committee IS NULL);

        IF partial_pair_count > 0 THEN
            RAISE EXCEPTION
                'cannot normalize committees: partial committee id/name rows exist: %',
                partial_pair_count;
        END IF;

        SELECT count(*) INTO id_conflict_count
        FROM (
            SELECT committee_id
            FROM bills
            WHERE committee_id IS NOT NULL
            GROUP BY committee_id
            HAVING count(DISTINCT committee) > 1
        ) conflicts;

        IF id_conflict_count > 0 THEN
            RAISE EXCEPTION
                'cannot normalize committees: committee_id maps to multiple names: %',
                id_conflict_count;
        END IF;

        SELECT count(*) INTO name_conflict_count
        FROM (
            SELECT committee
            FROM bills
            WHERE committee IS NOT NULL
            GROUP BY committee
            HAVING count(DISTINCT committee_id) > 1
        ) conflicts;

        IF name_conflict_count > 0 THEN
            RAISE EXCEPTION
                'cannot normalize committees: committee name maps to multiple ids: %',
                name_conflict_count;
        END IF;

        INSERT INTO committees (committee_id, committee_name)
        SELECT DISTINCT committee_id, committee
        FROM bills
        WHERE committee_id IS NOT NULL
          AND committee IS NOT NULL
        ON CONFLICT (committee_id) DO NOTHING;

        SELECT count(*) INTO existing_mismatch_count
        FROM bills b
        JOIN committees c ON c.committee_id = b.committee_id
        WHERE b.committee IS NOT NULL
          AND c.committee_name <> b.committee;

        IF existing_mismatch_count > 0 THEN
            RAISE EXCEPTION
                'cannot normalize committees: existing committees disagree with bills: %',
                existing_mismatch_count;
        END IF;
    END IF;

    SELECT count(*) INTO orphan_committee_id_count
    FROM bills b
    LEFT JOIN committees c ON c.committee_id = b.committee_id
    WHERE b.committee_id IS NOT NULL
      AND c.committee_id IS NULL;

    IF orphan_committee_id_count > 0 THEN
        RAISE EXCEPTION
            'cannot add bills.committee_id FK: missing committees rows: %',
            orphan_committee_id_count;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.bills'::regclass
          AND conname = 'bills_committee_id_fkey'
    ) THEN
        ALTER TABLE bills
            ADD CONSTRAINT bills_committee_id_fkey
            FOREIGN KEY (committee_id)
            REFERENCES committees (committee_id)
            ON DELETE RESTRICT;
    END IF;

    ALTER TABLE bills DROP COLUMN IF EXISTS committee;
END $$;

COMMENT ON TABLE committees IS
  'Bill-side committee/referral dimension. Preserves committee_id -> committee_name from bill source rows; not committee membership or history.';
COMMENT ON COLUMN committees.committee_id IS
  'PK. Bill-side committee/referral code used by bills.committee_id. May include 본회의 or special/referral bodies; not a member roster key.';
COMMENT ON COLUMN committees.committee_name IS
  'Display/source name for the bill-side committee/referral code. Unique in current 22대 data; aliases/history are separate future design if conflicts appear.';
COMMENT ON COLUMN bills.committee_id IS
  'Nullable FK to committees.committee_id. Bill-side committee/referral identity key; join committees for display name. Not equivalent to meetings.comm_name or committee membership.';
COMMENT ON COLUMN meetings.comm_name IS
  '회의 소관 위원회명 원문. bills.committee_id는 committees dimension으로 정규화됐지만 meetings.comm_name은 meeting-side 자유문자라 직접 FK가 아니다. 법안 소관과 연결할 때는 이름/공백 정규화 또는 별도 alias 설계가 필요하다.';
