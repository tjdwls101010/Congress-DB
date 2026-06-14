-- Congress-DB initial schema (Postgres 16)
-- Source: docs/design/ERD.md
-- 컬럼·테이블·함수 의미/함정 주석은 COMMENT로 migrations/011_schema_comments.sql에 있다(db-migrate가 적용).
-- 함정·어휘는 위 COMMENT에 있고(introspect로 보임), cross-table 레시피만 docs/design/DB-QUERY-GUIDE.md.
-- 9 core tables + 1 dimension table + 1 alias table + 1 outcome table + 3 ingest operational tables = 15 tables.
-- 자연키 우선, FK는 ON DELETE RESTRICT (참조 무결성 우선).
-- CREATE TABLE IF NOT EXISTS로 idempotent 적용 (변경은 db-reset 또는 향후 migrations/).
-- 적용은 psql -1 (single-transaction)으로 wrap — 이 파일에는 BEGIN/COMMIT 없음.

-- =========================================================================
-- 1. members — 의원 (자연키 PK)
-- =========================================================================
CREATE TABLE IF NOT EXISTS members (
    mona_cd         TEXT PRIMARY KEY,
    hg_nm           TEXT NOT NULL,
    hj_nm           TEXT,
    eng_nm          TEXT,
    bth_date        DATE,
    sex_gbn_nm      TEXT,
    poly_nm         TEXT,
    orig_nm         TEXT,
    units           TEXT,
    is_incumbent    BOOLEAN NOT NULL DEFAULT FALSE,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_members_hg_nm  ON members (hg_nm);
CREATE INDEX IF NOT EXISTS idx_members_poly_nm ON members (poly_nm);

-- =========================================================================
-- 2. meetings — 회의 (웹 HTML 회의록 기준, 자연키 PK = mnts_id)
-- =========================================================================
CREATE TABLE IF NOT EXISTS meetings (
    mnts_id         INT PRIMARY KEY,
    title           TEXT NOT NULL,
    meeting_type    TEXT NOT NULL
                    CHECK (meeting_type IN (
                        '본회의', '상임위', '특별위',
                        '국정감사', '국정조사', '인사청문회', '소위원회'
                    )),
    session_no      INT,
    conf_date       DATE NOT NULL,
    comm_name       TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meetings_date       ON meetings (conf_date DESC);
CREATE INDEX IF NOT EXISTS idx_meetings_type       ON meetings (meeting_type);
CREATE INDEX IF NOT EXISTS idx_meetings_comm       ON meetings (comm_name);
CREATE INDEX IF NOT EXISTS idx_meetings_type_date  ON meetings (meeting_type, conf_date DESC);

-- =========================================================================
-- 3. committees — 법안 소관 위원회/기관 차원
-- =========================================================================
CREATE TABLE IF NOT EXISTS committees (
    committee_id          TEXT PRIMARY KEY,
    committee_name        TEXT NOT NULL UNIQUE
);

-- =========================================================================
-- 4. bills — 법안
-- =========================================================================
CREATE TABLE IF NOT EXISTS bills (
    bill_id              TEXT PRIMARY KEY,
    bill_no              TEXT NOT NULL UNIQUE,
    bill_name            TEXT NOT NULL,
    propose_dt           DATE,
    proposer_raw         TEXT,
    committee_id         TEXT REFERENCES committees (committee_id) ON DELETE RESTRICT,
    proc_result          TEXT,
    proc_dt              DATE,
    law_proc_dt          DATE,
    committee_dt         DATE,
    cmt_proc_dt          DATE,
    cmt_proc_result      TEXT,
    summary              TEXT,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bills_propose_dt  ON bills (propose_dt DESC);
CREATE INDEX IF NOT EXISTS idx_bills_proc_result ON bills (proc_result);

-- =========================================================================
-- 5. bill_relations — 원안→대안/수정안 흡수 관계
-- =========================================================================
CREATE TABLE IF NOT EXISTS bill_relations (
    absorbed_bill_id     TEXT PRIMARY KEY REFERENCES bills (bill_id) ON DELETE RESTRICT,
    alternative_bill_id  TEXT NOT NULL,
    relation_type        TEXT NOT NULL
                         CHECK (relation_type IN ('대안반영', '수정안반영')),
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bill_relations_alternative
    ON bill_relations (alternative_bill_id);

-- =========================================================================
-- 5a. bill_source_aliases — source별 BILL_ID → canonical 법안 연결
-- =========================================================================
CREATE TABLE IF NOT EXISTS bill_source_aliases (
    source               TEXT NOT NULL,
    source_bill_id       TEXT NOT NULL,
    bill_no              TEXT,
    canonical_bill_id    TEXT REFERENCES bills (bill_id) ON DELETE RESTRICT,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_bill_id)
);

-- =========================================================================
-- 5b. bill_final_outcomes — 본회의 이후 정부이송·공포 이력
-- =========================================================================
CREATE TABLE IF NOT EXISTS bill_final_outcomes (
    bill_no              TEXT PRIMARY KEY REFERENCES bills (bill_no) ON DELETE RESTRICT,
    plenary_dt           DATE,
    govt_transfer_dt     DATE,
    promulgation_dt      DATE,
    prom_no              TEXT,
    prom_law_nm          TEXT,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =========================================================================
-- 6. bill_lead_proposers — 대표발의 N:M (PK: bill_id + mona_cd)
-- =========================================================================
CREATE TABLE IF NOT EXISTS bill_lead_proposers (
    bill_id   TEXT NOT NULL REFERENCES bills   (bill_id)   ON DELETE RESTRICT,
    mona_cd   TEXT NOT NULL REFERENCES members (mona_cd)   ON DELETE RESTRICT,
    order_no  SMALLINT,
    PRIMARY KEY (bill_id, mona_cd)
);

CREATE INDEX IF NOT EXISTS idx_lead_proposers_mona ON bill_lead_proposers (mona_cd);

-- =========================================================================
-- 7. bill_coproposers — 공동발의 N:M (PK: bill_id + mona_cd)
-- =========================================================================
CREATE TABLE IF NOT EXISTS bill_coproposers (
    bill_id   TEXT NOT NULL REFERENCES bills (bill_id)   ON DELETE RESTRICT,
    mona_cd   TEXT NOT NULL REFERENCES members (mona_cd) ON DELETE RESTRICT,
    order_no  SMALLINT,
    PRIMARY KEY (bill_id, mona_cd)
);

CREATE INDEX IF NOT EXISTS idx_coproposers_mona ON bill_coproposers (mona_cd);

-- =========================================================================
-- 8. votes — 본회의 표결 (시점 정당 박힘, PK = bill_id + mona_cd)
-- =========================================================================
CREATE TABLE IF NOT EXISTS votes (
    bill_id           TEXT NOT NULL REFERENCES bills (bill_id)   ON DELETE RESTRICT,
    mona_cd           TEXT NOT NULL REFERENCES members (mona_cd) ON DELETE RESTRICT,
    vote_date         TIMESTAMPTZ NOT NULL,
    result_vote_mod   TEXT NOT NULL,
    poly_nm_at_vote   TEXT,
    PRIMARY KEY (bill_id, mona_cd)
);

CREATE INDEX IF NOT EXISTS idx_votes_mona ON votes (mona_cd);
CREATE INDEX IF NOT EXISTS idx_votes_bill ON votes (bill_id);
CREATE INDEX IF NOT EXISTS idx_votes_date ON votes (vote_date DESC);

-- =========================================================================
-- 9. utterances — 발언 (FK → meetings, members)
-- =========================================================================
CREATE TABLE IF NOT EXISTS utterances (
    id                  BIGSERIAL PRIMARY KEY,
    meeting_id          INT  NOT NULL REFERENCES meetings       (mnts_id) ON DELETE RESTRICT,
    sequence            INT  NOT NULL,
    speaker_name        TEXT NOT NULL,
    speaker_title       TEXT NOT NULL,
    speaker_mona_cd     TEXT REFERENCES members        (mona_cd) ON DELETE RESTRICT,
    speaker_role        TEXT NOT NULL
                        CHECK (speaker_role IN (
                            '의원', '국무위원(장관)', '차관',
                            '증인', '참고인', '전문위원', '기타'
                        )),
    content             TEXT NOT NULL,
    UNIQUE (meeting_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_utterances_meeting       ON utterances (meeting_id);
CREATE INDEX IF NOT EXISTS idx_utterances_speaker       ON utterances (speaker_mona_cd) WHERE speaker_mona_cd IS NOT NULL;

-- =========================================================================
-- 10. meeting_bills — 회의↔법안 N:M junction
-- =========================================================================
CREATE TABLE IF NOT EXISTS meeting_bills (
    meeting_id  INT  NOT NULL REFERENCES meetings (mnts_id) ON DELETE RESTRICT,
    bill_id     TEXT NOT NULL REFERENCES bills    (bill_id) ON DELETE RESTRICT,
    PRIMARY KEY (meeting_id, bill_id)
);

CREATE INDEX IF NOT EXISTS idx_mb_bill ON meeting_bills (bill_id);

-- =========================================================================
-- 11. ingest_runs — 수집 실행 기록
-- =========================================================================
CREATE TABLE IF NOT EXISTS ingest_runs (
    id              BIGSERIAL PRIMARY KEY,
    mode            TEXT NOT NULL
                    CHECK (mode IN ('backfill', 'incremental', 'dead_letter_retry')),
    status          TEXT NOT NULL
                    CHECK (status IN (
                        'running', 'success', 'degraded_success',
                        'failed', 'blocked'
                    )),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    overlap_days    INT CHECK (overlap_days IS NULL OR overlap_days >= 0),
    window_start    TIMESTAMPTZ,
    window_end      TIMESTAMPTZ,
    summary         JSONB NOT NULL DEFAULT '{}'::jsonb,
    error           TEXT,
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK (window_start IS NULL OR window_end IS NULL OR window_end >= window_start)
);

CREATE INDEX IF NOT EXISTS idx_ingest_runs_mode_started
    ON ingest_runs (mode, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_status_started
    ON ingest_runs (status, started_at DESC);

-- =========================================================================
-- 12. ingest_cursors — source별 증분 기준점
-- =========================================================================
CREATE TABLE IF NOT EXISTS ingest_cursors (
    source          TEXT PRIMARY KEY,
    cursor_kind     TEXT NOT NULL,
    cursor_value    TIMESTAMPTZ,
    overlap_days    INT NOT NULL DEFAULT 30 CHECK (overlap_days >= 0),
    updated_run_id  BIGINT REFERENCES ingest_runs (id) ON DELETE RESTRICT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ingest_cursors_updated_run
    ON ingest_cursors (updated_run_id);

-- =========================================================================
-- 13. dead_letters — 실패 item 보존
-- =========================================================================
CREATE TABLE IF NOT EXISTS dead_letters (
    id               BIGSERIAL PRIMARY KEY,
    run_id           BIGINT NOT NULL REFERENCES ingest_runs (id) ON DELETE RESTRICT,
    source           TEXT NOT NULL,
    stage            TEXT NOT NULL,
    item_key         TEXT NOT NULL,
    payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    error            TEXT NOT NULL,
    attempts         INT NOT NULL DEFAULT 1 CHECK (attempts > 0),
    status           TEXT NOT NULL
                     CHECK (status IN (
                         'pending', 'retrying', 'resolved', 'ignored', 'blocked'
                     )),
    first_failed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_failed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at      TIMESTAMPTZ,
    CHECK (last_failed_at >= first_failed_at),
    CHECK (
        (status IN ('resolved', 'ignored') AND resolved_at IS NOT NULL)
        OR (status NOT IN ('resolved', 'ignored'))
    )
);

CREATE INDEX IF NOT EXISTS idx_dead_letters_run_id
    ON dead_letters (run_id);
CREATE INDEX IF NOT EXISTS idx_dead_letters_status_last_failed
    ON dead_letters (status, last_failed_at);
CREATE INDEX IF NOT EXISTS idx_dead_letters_source_item
    ON dead_letters (source, item_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dead_letters_unresolved_unique
    ON dead_letters (source, stage, item_key)
    WHERE status IN ('pending', 'retrying', 'blocked');
