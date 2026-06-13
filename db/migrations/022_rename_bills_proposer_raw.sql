-- 022_rename_bills_proposer_raw.sql — source wording임을 드러내도록 bills.proposer rename
--
-- #117/#121 decision: proposer identity의 정본은 bill_lead_proposers /
-- bill_coproposers이고, 국회 API PROPOSER 텍스트는 join으로 복원되지 않는
-- '외 N인' 같은 source wording을 보존하는 raw field다.

DO $$
DECLARE
    has_proposer BOOLEAN;
    has_proposer_raw BOOLEAN;
    has_conflicting_values BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'bills'
          AND column_name = 'proposer'
    )
    INTO has_proposer;

    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'bills'
          AND column_name = 'proposer_raw'
    )
    INTO has_proposer_raw;

    IF has_proposer AND has_proposer_raw THEN
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM bills WHERE proposer IS DISTINCT FROM proposer_raw)'
        INTO has_conflicting_values;

        IF has_conflicting_values THEN
            RAISE EXCEPTION
                'Cannot drop bills.proposer because bills.proposer_raw exists with different values';
        END IF;

        ALTER TABLE bills DROP COLUMN proposer;
    ELSIF has_proposer THEN
        ALTER TABLE bills RENAME COLUMN proposer TO proposer_raw;
    ELSIF NOT has_proposer_raw THEN
        RAISE EXCEPTION 'Expected either bills.proposer or bills.proposer_raw to exist';
    END IF;
END $$;

COMMENT ON COLUMN bills.proposer_raw IS
  '국회 API PROPOSER 원천 문구(예: ''홍길동의원 등 17인''). 대표/공동발의자 member identity 정본이 아니며, 정확한 의원 join은 bill_lead_proposers·bill_coproposers를 쓸 것. ''외 N인'' 등 join으로 복원되지 않는 원천 표현·서명자 수 힌트 보존용이므로 members에 파싱 join하지 말 것.';
