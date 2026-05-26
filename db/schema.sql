-- Congress-DB initial schema (Postgres 16)
-- Source: docs/ERD.md
-- 10 core tables + 1 catalog table = 11 tables.
-- 자연키 우선, FK는 ON DELETE RESTRICT (참조 무결성 우선).
-- CREATE TABLE IF NOT EXISTS로 idempotent 적용 (변경은 db-reset 또는 향후 migrations/).

BEGIN;

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
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_members_hg_nm  ON members (hg_nm);
CREATE INDEX IF NOT EXISTS idx_members_poly_nm ON members (poly_nm);

-- =========================================================================
-- 2. meetings — 회의 (5종 통합, 자연키 PK = mnts_id)
-- =========================================================================
CREATE TABLE IF NOT EXISTS meetings (
    mnts_id         INT PRIMARY KEY,
    conf_id         TEXT,
    title           TEXT NOT NULL,
    meeting_type    TEXT NOT NULL
                    CHECK (meeting_type IN (
                        '본회의', '상임위', '특별위',
                        '국정감사', '국정조사', '인사청문회', '소위원회'
                    )),
    class_name      TEXT,
    dae_num         SMALLINT NOT NULL DEFAULT 22,
    session_no      INT,
    degree          TEXT,
    conf_date       DATE NOT NULL,
    comm_name       TEXT,
    comm_code       TEXT,
    pdf_link_url    TEXT,
    vod_link_url    TEXT,
    conf_link_url   TEXT,
    source_api      TEXT NOT NULL,
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
    detail_link          TEXT,
    age                  SMALLINT NOT NULL DEFAULT 22,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bills_rst         ON bills (rst_mona_cd);
CREATE INDEX IF NOT EXISTS idx_bills_propose_dt  ON bills (propose_dt DESC);
CREATE INDEX IF NOT EXISTS idx_bills_proc_result ON bills (proc_result);

-- =========================================================================
-- 5. bill_coproposers — 공동발의 N:M (PK: bill_id + mona_cd)
-- =========================================================================
CREATE TABLE IF NOT EXISTS bill_coproposers (
    bill_id   TEXT NOT NULL REFERENCES bills (bill_id)   ON DELETE RESTRICT,
    mona_cd   TEXT NOT NULL REFERENCES members (mona_cd) ON DELETE RESTRICT,
    order_no  SMALLINT,
    PRIMARY KEY (bill_id, mona_cd)
);

CREATE INDEX IF NOT EXISTS idx_coproposers_mona ON bill_coproposers (mona_cd);

-- =========================================================================
-- 6. votes — 본회의 표결 (시점 정당 박힘, UNIQUE(bill_id, mona_cd))
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
-- 7. session_groups — Q&A 그룹 (FK → meetings, members)
-- =========================================================================
CREATE TABLE IF NOT EXISTS session_groups (
    id                    BIGSERIAL PRIMARY KEY,
    meeting_id            INT  NOT NULL REFERENCES meetings (mnts_id) ON DELETE RESTRICT,
    questioner_mona_cd    TEXT NOT NULL REFERENCES members  (mona_cd) ON DELETE RESTRICT,
    respondents           JSONB,
    seq_start             INT NOT NULL,
    seq_end               INT NOT NULL,
    utterance_count       INT NOT NULL,
    total_chars           INT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sg_meeting    ON session_groups (meeting_id);
CREATE INDEX IF NOT EXISTS idx_sg_questioner ON session_groups (questioner_mona_cd);

-- =========================================================================
-- 8. utterances — 발언 (FK → meetings, members, session_groups)
-- =========================================================================
CREATE TABLE IF NOT EXISTS utterances (
    id                  BIGSERIAL PRIMARY KEY,
    meeting_id          INT  NOT NULL REFERENCES meetings       (mnts_id) ON DELETE RESTRICT,
    sequence            INT  NOT NULL,
    speaker_name        TEXT NOT NULL,
    speaker_title       TEXT NOT NULL,
    speaker_mona_cd     TEXT REFERENCES members        (mona_cd) ON DELETE RESTRICT,
    content             TEXT NOT NULL,
    session_group_id    BIGINT REFERENCES session_groups (id)    ON DELETE RESTRICT,
    UNIQUE (meeting_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_utterances_meeting       ON utterances (meeting_id);
CREATE INDEX IF NOT EXISTS idx_utterances_speaker       ON utterances (speaker_mona_cd) WHERE speaker_mona_cd IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_utterances_session_group ON utterances (session_group_id) WHERE session_group_id IS NOT NULL;

-- =========================================================================
-- 9. agenda_items — 회의 안건 (FK → meetings, bills)
-- =========================================================================
CREATE TABLE IF NOT EXISTS agenda_items (
    id          BIGSERIAL PRIMARY KEY,
    meeting_id  INT  NOT NULL REFERENCES meetings (mnts_id) ON DELETE RESTRICT,
    order_no    SMALLINT,
    sub_name    TEXT NOT NULL,
    bill_id     TEXT REFERENCES bills (bill_id) ON DELETE RESTRICT,
    UNIQUE (meeting_id, order_no, sub_name)
);

CREATE INDEX IF NOT EXISTS idx_agenda_meeting ON agenda_items (meeting_id);
CREATE INDEX IF NOT EXISTS idx_agenda_bill    ON agenda_items (bill_id) WHERE bill_id IS NOT NULL;

-- =========================================================================
-- 10. meeting_bills — 회의↔법안 N:M junction
-- =========================================================================
CREATE TABLE IF NOT EXISTS meeting_bills (
    meeting_id  INT  NOT NULL REFERENCES meetings (mnts_id) ON DELETE RESTRICT,
    bill_id     TEXT NOT NULL REFERENCES bills    (bill_id) ON DELETE RESTRICT,
    source      TEXT,
    PRIMARY KEY (meeting_id, bill_id)
);

CREATE INDEX IF NOT EXISTS idx_mb_bill ON meeting_bills (bill_id);

COMMIT;
