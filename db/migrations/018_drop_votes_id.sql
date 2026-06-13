-- 018_drop_votes_id.sql — votes row identity를 자연키로 전환
--
-- Current source grain is one row per bill-member pair. Existing live data had
-- zero duplicate (bill_id, mona_cd) groups at audit time, so the surrogate id
-- is removed and the natural key becomes the primary key.

DO $$
DECLARE
    duplicate_count integer;
BEGIN
    SELECT count(*) INTO duplicate_count
    FROM (
        SELECT bill_id, mona_cd
        FROM votes
        GROUP BY bill_id, mona_cd
        HAVING count(*) > 1
    ) duplicates;

    IF duplicate_count > 0 THEN
        RAISE EXCEPTION
            'cannot drop votes.id: duplicate (bill_id, mona_cd) groups exist: %',
            duplicate_count;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'votes'
          AND column_name = 'id'
    ) THEN
        ALTER TABLE votes DROP CONSTRAINT IF EXISTS votes_pkey;
        ALTER TABLE votes DROP CONSTRAINT IF EXISTS votes_bill_id_mona_cd_key;
        ALTER TABLE votes ADD CONSTRAINT votes_pkey PRIMARY KEY (bill_id, mona_cd);
        ALTER TABLE votes DROP COLUMN id;
    ELSIF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.votes'::regclass
          AND contype = 'p'
    ) THEN
        ALTER TABLE votes ADD CONSTRAINT votes_pkey PRIMARY KEY (bill_id, mona_cd);
    END IF;
END $$;
