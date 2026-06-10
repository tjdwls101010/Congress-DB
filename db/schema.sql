-- Congress-DB initial schema (Postgres 16)
-- Source: docs/design/ERD.md
-- 9 core tables + 1 audit table + 1 catalog table + 3 ingest operational tables = 14 tables.
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
    elect_gbn_nm    TEXT,
    cmits           TEXT,
    reele_gbn_nm    TEXT,
    units           TEXT,
    tel_no          TEXT,
    e_mail          TEXT,
    homepage        TEXT,
    mem_title       TEXT,
    assem_addr      TEXT,
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
    degree          TEXT,
    conf_date       DATE NOT NULL,
    comm_name       TEXT,
    is_temporary    BOOLEAN NOT NULL DEFAULT FALSE,
    is_appendix     BOOLEAN NOT NULL DEFAULT FALSE,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meetings_date       ON meetings (conf_date DESC);
CREATE INDEX IF NOT EXISTS idx_meetings_type       ON meetings (meeting_type);
CREATE INDEX IF NOT EXISTS idx_meetings_comm       ON meetings (comm_name);
CREATE INDEX IF NOT EXISTS idx_meetings_type_date  ON meetings (meeting_type, conf_date DESC);

-- =========================================================================
-- 3. api_catalog — 277개 API 1회성 검증 결과 (no FK)
-- =========================================================================
CREATE TABLE IF NOT EXISTS api_catalog (
    inf_id              TEXT PRIMARY KEY,
    name                TEXT,
    endpoint            TEXT,
    source_system       TEXT,
    category            TEXT,
    tested_at           TIMESTAMPTZ,
    status              TEXT,
    has_22nd_data       BOOLEAN,
    total_count_22nd    INT,
    used_in_pipeline    BOOLEAN NOT NULL DEFAULT FALSE,
    usage_note          TEXT,
    skip_reason         TEXT
);

-- =========================================================================
-- 4. bills — 법안 (FK → members)
-- =========================================================================
CREATE TABLE IF NOT EXISTS bills (
    bill_id              TEXT PRIMARY KEY,
    bill_no              TEXT NOT NULL UNIQUE,
    bill_name            TEXT NOT NULL,
    propose_dt           DATE,
    rst_mona_cd          TEXT REFERENCES members (mona_cd) ON DELETE RESTRICT,
    rst_proposer         TEXT,
    publ_proposer        TEXT,
    proposer             TEXT,
    committee            TEXT,
    committee_id         TEXT,
    proc_result          TEXT,
    proc_dt              DATE,
    law_proc_dt          DATE,
    law_proc_result_cd   TEXT,
    committee_dt         DATE,
    cmt_proc_dt          DATE,
    cmt_proc_result_cd   TEXT,
    summary              TEXT,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bills_rst         ON bills (rst_mona_cd);
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
    source               TEXT NOT NULL DEFAULT 'likms_selrefbillid',
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bill_relations_alternative
    ON bill_relations (alternative_bill_id);

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
-- 8. votes — 본회의 표결 (시점 정당 박힘, UNIQUE(bill_id, mona_cd))
-- =========================================================================
CREATE TABLE IF NOT EXISTS votes (
    id                BIGSERIAL PRIMARY KEY,
    bill_id           TEXT NOT NULL REFERENCES bills (bill_id)   ON DELETE RESTRICT,
    mona_cd           TEXT NOT NULL REFERENCES members (mona_cd) ON DELETE RESTRICT,
    vote_date         TIMESTAMPTZ NOT NULL,
    result_vote_mod   TEXT NOT NULL,
    poly_nm_at_vote   TEXT,
    session_cd        INT,
    currents_cd       INT,
    UNIQUE (bill_id, mona_cd)
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
-- 9a. speaker_title_role_map — raw 직함→발언 역할 audit
-- =========================================================================
CREATE TABLE IF NOT EXISTS speaker_title_role_map (
    speaker_title   TEXT PRIMARY KEY,
    speaker_role    TEXT NOT NULL
                    CHECK (speaker_role IN (
                        '의원', '국무위원(장관)', '차관',
                        '증인', '참고인', '전문위원', '기타'
                    )),
    n_utterances    BIGINT NOT NULL DEFAULT 0 CHECK (n_utterances >= 0),
    n_no_mona       BIGINT NOT NULL DEFAULT 0 CHECK (n_no_mona >= 0),
    n_mona          BIGINT NOT NULL DEFAULT 0 CHECK (n_mona >= 0),
    classified_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (n_utterances = n_no_mona + n_mona)
);

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
