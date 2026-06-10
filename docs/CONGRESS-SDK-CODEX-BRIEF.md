# Congress-SDK Codex Brief

> **⚠️ OBSOLETE (2026-06-10):** 여기 기술된 국회 SDK는 **만들지 않는다.** DECISIONS 2026-06-10에 따라,
> 향후 입법전문가 스킬은 별도 SDK repo 대신 이 DB의 스키마 레퍼런스를 보고 read-only SQL로 Neon을 직접
> 조회한다. 이 문서는 역사적 맥락 + DB 레퍼런스로 보존한다(스키마 요약·베이스라인·canonical 쿼리는 여전히
> 유효). 단 'congress-sdk repo 생성 / SDK v1 방향 / vertical slice' 프레이밍은 폐기됐다.

This document is the handoff brief for creating a new repository named
`congress-sdk`.

The new repository may not have access to this `Congress-DB` codebase. Treat this
file as the initial project context to give Codex before grilling, specs, issues,
and implementation.

Last updated: 2026-06-06.

## Copy-Paste Prompt For The New Repo

You are Codex working in a new repository named `congress-sdk`.

The product goal is to build the SDK layer for a later Codex skill called
`입법전문가 스킬` ("legislative expert skill"). The SDK should make a hosted
Postgres database of South Korea National Assembly data easy and safe for agents
and applications to query.

The source database was built in a separate repository, `Congress-DB`. That repo
normalized fragmented National Assembly OpenAPI and meeting-record HTML sources
into Neon Postgres. You cannot assume access to the old repo. You must discover
the live database schema yourself from Neon and then grill the PM before
designing the SDK.

High-level DB purpose:

- Scope: South Korea 22nd National Assembly term, starting 2024-05-30.
- Core entities: Member, Bill, Meeting, Utterance, Vote.
- Core value: one stable natural key can retrieve a member's bills, votes, and
  meeting utterances; a bill's proposers, votes, meetings, and alternative
  relations; a meeting's bills and utterance stream.
- The DB stores proposed bills and legislative activity. It does not store
  currently effective statutes, enforcement decrees, official interpretations,
  precedents, or Constitutional Court decisions. Those belong to a later
  `법제처 SDK`.

Hosted DB facts:

- Provider: Neon Launch.
- Organization: `Seongjin` (`org-rapid-heart-55745998`).
- Project: `congress-db-staging` (`wispy-night-08362506`).
- Region: `aws-ap-southeast-1`.
- Database: `congress`.
- Role used during migration: `congress_owner`.
- Postgres version: `17.10`.
- The DB is migrated, restored, analyzed, and smoke-tested.
- Hosted incremental smoke run: `ingest_runs.id = 753`, status `success`,
  dead letters `0`.

Security and connection rules:

- Never commit or print Neon connection strings.
- Use environment variables only.
- This brief intentionally does not contain the database URL. The SDK needs a
  Neon connection string at runtime, but it must be retrieved from Neon tooling
  or supplied locally by the PM.
- SDK/server runtime should use the Neon pooled connection string.
- Restore, backup, schema migration, and native ingest tooling should use the
  direct non-pooled connection string.
- Do not enable or depend on Neon Data API for SDK v1. It exposes schema over
  HTTP and needs explicit RLS/GRANT/view design. Start with direct server-side
  Postgres access through the SDK.
- Do not expose the database connection string to browsers or untrusted agents.
- Prefer a read-only database role for the SDK. If only `congress_owner` is
  available initially, keep it server-side and treat least-privilege role
  creation as an early issue.

Before coding:

1. Grill the PM on the SDK's public interface, result shapes, packaging language,
   runtime targets, and which legislative workflows matter first.
2. Discover the live Neon schema by connecting to Neon and introspecting the DB.
3. Produce `CONTEXT.md`, `docs/design/PRD.md`, `docs/design/IA.md`, and
   `docs/design/DECISIONS.md` in the new repo.
4. Break implementation into thin vertical-slice GitHub issues.
5. Only then implement with TDD.

Recommended SDK v1 direction:

- Build a read-oriented SDK, not another ingest pipeline.
- Start with deep modules that map directly to domain workflows:
  - `searchBills(query, options)`
  - `getBill(ref, options)`
  - `getBillHistory(ref, options)`
  - `searchUtterances(query, options)`
  - `getUtteranceContext(ref, window)`
  - `getMeeting(ref, options)`
  - `getMember(ref, options)`
  - `getMemberActivity(ref, options)`
  - `getVoteSummary(billRef, options)`
- Every result must preserve evidence keys: `bill_id`, `bill_no`, `mona_cd`,
  `mnts_id`, `utterance_id`, `sequence`, and dates.
- Nulls are meaningful. Do not fabricate dates, proposer IDs, summaries, party
  names, or speaker mappings.
- Return enough metadata for an agent to cite what it saw and ask follow-up
  queries deterministically.
- Page or limit utterance-heavy results. A single meeting can have thousands of
  utterances.
- Start with existing DB search functions and SQL joins. Do not add embeddings,
  a vector store, or a semantic topic layer until a measured retrieval failure
  justifies it.

Recommended first vertical slices:

1. DB connection and schema discovery report.
   - Given a Neon `DATABASE_URL`, the SDK can connect, run a health check, and
     generate a local schema/introspection report without leaking secrets.
2. Bill keyword search.
   - Given a Korean query such as `전세사기`, the SDK returns ranked bills with
     snippets, identifiers, dates, committee, processing status, and nullable
     fields represented honestly.
3. Bill detail and legislative history.
   - Given `bill_id` or `bill_no`, the SDK returns the bill, lead/co-proposers,
     alternative relation if any, meetings where it was discussed, and vote
     summary if voted.
4. Utterance search with context window.
   - Given a Korean query, the SDK returns utterance hits plus neighboring
     utterances in the same `meeting_id` by `sequence`.
5. Member activity profile.
   - Given `mona_cd` or an unambiguous Korean name, the SDK returns member
     profile, lead bills, co-sponsored bills, votes, and utterance activity.

The later `입법전문가 스킬` should use this SDK to answer questions like:

- "이 사회문제와 관련된 22대 법안은 무엇이고 어떻게 처리됐나?"
- "어떤 의원이 이 의제에 발의, 표결, 발언으로 관여했나?"
- "이 법안은 어떤 회의에서 어떤 맥락으로 논의됐나?"
- "대안반영폐기된 원안은 어떤 대안/수정안에 흡수됐나?"
- "법안명/요약 검색 결과와 회의록 발언 증거를 함께 보여줘."

## Neon Access And Schema Discovery

Use the `neon-postgres` skill if it is available in the new Codex environment.
If Neon MCP tools are available, prefer them for listing projects, getting
connection strings, and running read-only SQL. If not, use `neonctl`.

This document is enough context to identify the correct Neon project, but it is
not itself a credential. One of these must be true before the new SDK repo can
connect:

- The local machine already has an authenticated `neonctl` session for the
  `Seongjin` organization.
- The new Codex environment has a configured Neon MCP connection with permission
  to access project `wispy-night-08362506`.
- The PM manually provides the pooled Neon URL in a local, gitignored env file.

Initialize Neon tooling if the new repo does not already have it:

```sh
npx -y neonctl@latest init --agent codex
```

Inspect the account and project:

```sh
npx -y neonctl@latest orgs list
npx -y neonctl@latest projects list --org-id org-rapid-heart-55745998
npx -y neonctl@latest projects get wispy-night-08362506
```

Get the pooled connection string for SDK/runtime reads:

```sh
npx -y neonctl@latest connection-string main \
  --project-id wispy-night-08362506 \
  --database-name congress \
  --role-name congress_owner \
  --pooled \
  --ssl require
```

Get the direct non-pooled connection string only for admin tools:

```sh
npx -y neonctl@latest connection-string main \
  --project-id wispy-night-08362506 \
  --database-name congress \
  --role-name congress_owner \
  --ssl require
```

Store secrets locally, not in git:

```sh
# Example only. Do not commit this file.
printf 'DATABASE_URL=%s\n' '<pooled-neon-url>' > .env.local
```

If `neonctl connection-string` succeeds, use its pooled output as
`DATABASE_URL`. If it fails because the new environment is not authenticated,
ask the PM to either finish Neon login or paste the pooled URL into `.env.local`
outside git.

Basic health check:

```sh
psql "$DATABASE_URL" -c "SELECT current_database(), current_user, version();"
```

List public tables:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
ORDER BY table_name;
```

List columns and nullability:

```sql
SELECT table_name, ordinal_position, column_name, data_type, is_nullable,
       column_default
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

List constraints and foreign keys:

```sql
SELECT
  tc.table_name,
  tc.constraint_name,
  tc.constraint_type,
  kcu.column_name,
  ccu.table_name AS foreign_table_name,
  ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints tc
LEFT JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
LEFT JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = tc.constraint_name
 AND ccu.table_schema = tc.table_schema
WHERE tc.table_schema = 'public'
ORDER BY tc.table_name, tc.constraint_type, tc.constraint_name, kcu.ordinal_position;
```

List indexes:

```sql
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
```

List SDK-relevant SQL functions:

```sql
SELECT p.proname, pg_get_functiondef(p.oid) AS function_definition
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname IN ('search_snippet', 'search_bills', 'search_utterances')
ORDER BY p.proname;
```

Get approximate row counts:

```sql
SELECT relname AS table_name, n_live_tup::bigint AS approximate_rows
FROM pg_stat_user_tables
ORDER BY relname;
```

Optional schema-only dump for local documentation:

```sh
pg_dump "$DATABASE_URL" \
  --schema-only \
  --no-owner \
  --no-privileges \
  > docs/neon-schema.sql
```

Review the dump before committing. It should contain no credentials.

## Current Hosted Baseline

After the hosted restore and incremental smoke, the operational baseline is:

| Table | Rows |
|---|---:|
| `members` | 320 |
| `bills` | 18,361 |
| `bill_relations` | 3,715 |
| `bill_lead_proposers` | 17,559 |
| `bill_coproposers` | 206,299 |
| `votes` | 473,594 |
| `meetings` | 2,105 |
| `meeting_bills` | 40,345 |
| `utterances` | 1,378,280 |

Data quality signals to preserve in SDK semantics:

| Signal | Value | Meaning |
|---|---:|---|
| `members_missing_party` | 20 | Referenced member stubs have enough identity for joins but profile party metadata is absent. |
| `bills_missing_propose_dt` | 1,028 | Vote/meeting-discovered bills have source metadata gaps. |
| `bills_missing_summary` | 253 | Bill-name search still works, but summary recall is incomplete for these rows. |
| `member_titled_utterances_unmapped` | 9 | Very small residual member-title mapping gap. |
| `overall_utterance_mapping_rate_pct` | 61.49 | Expected: many utterances are ministers, witnesses, staff, and other non-member speakers. |
| `member_titled_utterance_mapping_rate_pct` | 100.0 | Member-like titles are effectively mapped; do not judge by whole-corpus mapping rate. |

## Domain Glossary

Use these words consistently in code, docs, and issue bodies.

**Member / 의원**:
National Assembly member. Natural key: `members.mona_cd` (`MONA_CD`).

**Bill / 법안**:
Proposed bill or National Assembly agenda item represented in the DB. Natural
key: `bills.bill_id` (`BILL_ID`, `PRC_...`). Human-readable key:
`bills.bill_no` (`BILL_NO`, seven digits). Do not confuse this with currently
effective law.

**Lead Proposer / 대표발의자**:
Member listed as lead proposer. Multiple lead proposers are possible, so
`bill_lead_proposers` is the source of truth. `bills.rst_mona_cd` is only a
convenience FK when there is exactly one lead proposer.

**Co-proposer / 공동발의자**:
N:M relation between members and bills in `bill_coproposers`.

**Vote / 표결**:
Plenary vote only. Committee-stage votes are out of scope. One voted bill creates
one row per member in `votes`.

**Meeting / 회의**:
One meeting-record instance. Natural key: `meetings.mnts_id`, taken from the
HTML meeting record URL `id`.

**Utterance / 발언**:
One speaker turn in a meeting record. Ordered by `meeting_id + sequence`. Member
speakers join through nullable `speaker_mona_cd`; non-member speakers are
expected to have NULL `speaker_mona_cd`.

**Alternative Relation / 대안 관계**:
Connection from an absorbed original bill to the alternative/amendment source
key that absorbed it. Stored in `bill_relations(absorbed_bill_id,
alternative_bill_id, relation_type)`.

**Policy Topic / 정책 의제**:
A user search concept such as `전세사기`, `의대정원`, or `AI 기본법`. The DB does not
store a topic layer yet. SDK v1 should retrieve evidence; topic modeling is a
later layer.

**Neighbor Window / 주변 발언 창**:
The nearby utterances before and after a search hit in the same meeting ordered
by `sequence`. The DB intentionally does not pre-store Q&A groups or agenda
segments.

## Schema Summary

The live DB is the source of truth. Use introspection to confirm the latest
shape. As of the migration, the important tables are:

### `members`

National Assembly member profile and incumbency.

Important columns:

- `mona_cd` PK
- `hg_nm`
- `poly_nm`
- `orig_nm`
- `cmits`
- `reele_gbn_nm`
- `is_incumbent`

### `bills`

Bill search and status axis.

Important columns:

- `bill_id` PK
- `bill_no` UNIQUE
- `bill_name`
- `propose_dt` nullable
- `rst_mona_cd` nullable convenience FK
- `rst_proposer`, `publ_proposer`, `proposer`
- `committee`, `committee_id`
- `proc_result`, `proc_dt`
- `law_proc_dt`, `law_proc_result_cd`
- `committee_dt`, `cmt_proc_dt`, `cmt_proc_result_cd`
- `summary` nullable

Only `bill_id`, `bill_no`, and `bill_name` are guaranteed core identifiers.
Treat most other fields as nullable.

### `bill_lead_proposers`

Normalized lead proposer relation.

- PK: `(bill_id, mona_cd)`
- `order_no`

### `bill_coproposers`

Normalized co-proposer relation.

- PK: `(bill_id, mona_cd)`
- `order_no`

### `bill_relations`

Absorbed original bill to alternative/amendment source key.

- `absorbed_bill_id` PK, FK to `bills.bill_id`
- `alternative_bill_id` not necessarily FK to `bills`
- `relation_type`: `대안반영` or `수정안반영`

This asymmetry is intentional. Some alternatives exposed by source pages do not
exist as rows in `bills`.

### `votes`

Plenary vote rows.

- `bill_id`
- `mona_cd`
- `vote_date`
- `result_vote_mod`: e.g. `찬성`, `반대`, `기권`, `불참`
- `poly_nm_at_vote`
- UNIQUE `(bill_id, mona_cd)`

Use `poly_nm_at_vote` for vote-time party. Do not substitute it for
`members.poly_nm`.

### `meetings`

Meeting metadata.

- `mnts_id` PK
- `title`
- `meeting_type`: `본회의`, `상임위`, `특별위`, `국정감사`, `국정조사`, `인사청문회`, `소위원회`
- `conf_date`
- `comm_name`
- `session_no`
- `degree`

### `meeting_bills`

N:M relation between meetings and bills.

- PK: `(meeting_id, bill_id)`

### `utterances`

Meeting utterance stream.

- `id` PK
- `meeting_id`
- `sequence`
- `speaker_name`
- `speaker_title`
- `speaker_mona_cd` nullable
- `content`
- UNIQUE `(meeting_id, sequence)`

### Operational Tables

The SDK should normally read, not mutate:

- `api_catalog`
- `ingest_runs`
- `ingest_cursors`
- `dead_letters`

Operational status can be surfaced in admin/diagnostic APIs later, but do not
make it part of the user-facing SDK v1 unless the PM explicitly asks.

## Existing Search Functions

The DB includes `pg_trgm` indexes and stable SQL functions:

```sql
search_snippet(source_text TEXT, query_text TEXT, radius INT DEFAULT 80)
search_bills(query_text TEXT, result_limit INT DEFAULT 50)
search_utterances(query_text TEXT, result_limit INT DEFAULT 50)
```

Start SDK search on top of these functions.

`search_bills` returns:

- `bill_id`
- `bill_no`
- `bill_name`
- `propose_dt`
- `snippet`
- `similarity_score`

`search_utterances` returns:

- `utterance_id`
- `meeting_id`
- `sequence`
- `speaker_name`
- `speaker_title`
- `snippet`
- `similarity_score`

For utterance search, the SDK should usually add meeting metadata and a neighbor
window query around each hit.

## Canonical Query Patterns

### Bill Search

```sql
SELECT *
FROM search_bills($1, $2);
```

### Utterance Search With Meeting Metadata

```sql
SELECT s.*, m.title, m.conf_date, m.meeting_type, m.comm_name
FROM search_utterances($1, $2) s
JOIN meetings m ON m.mnts_id = s.meeting_id;
```

### Utterance Neighbor Window

```sql
SELECT u.id, u.meeting_id, u.sequence, u.speaker_name, u.speaker_title,
       u.speaker_mona_cd, u.content
FROM utterances u
WHERE u.meeting_id = $1
  AND u.sequence BETWEEN $2 - $3 AND $2 + $3
ORDER BY u.sequence;
```

### Bill Detail

```sql
SELECT *
FROM bills
WHERE bill_id = $1 OR bill_no = $1
LIMIT 1;
```

### Bill Proposers

```sql
SELECT 1 AS role_order, 'lead' AS role, lp.order_no, m.mona_cd, m.hg_nm, m.poly_nm
FROM bill_lead_proposers lp
JOIN members m USING (mona_cd)
WHERE lp.bill_id = $1
UNION ALL
SELECT 2 AS role_order, 'co' AS role, cp.order_no, m.mona_cd, m.hg_nm, m.poly_nm
FROM bill_coproposers cp
JOIN members m USING (mona_cd)
WHERE cp.bill_id = $1
ORDER BY role_order, order_no NULLS LAST, hg_nm;
```

### Bill Meetings

```sql
SELECT m.mnts_id, m.title, m.meeting_type, m.conf_date, m.comm_name
FROM meeting_bills mb
JOIN meetings m ON m.mnts_id = mb.meeting_id
WHERE mb.bill_id = $1
ORDER BY m.conf_date, m.mnts_id;
```

### Vote Summary

```sql
SELECT result_vote_mod, COUNT(*)::int AS count
FROM votes
WHERE bill_id = $1
GROUP BY result_vote_mod
ORDER BY result_vote_mod;
```

### Member Activity

```sql
SELECT m.*
FROM members m
WHERE m.mona_cd = $1 OR m.hg_nm = $1;
```

For names, handle ambiguity explicitly. Korean names are not guaranteed unique.
If multiple members match, return candidates and ask the caller to choose by
`mona_cd`.

## Grilling Checklist For The PM

Use `AskUserQuestion` if the environment provides it.

Do not ask which workflow phase applies. Start with grilling because this is a
new SDK.

Questions to resolve before specs:

1. SDK language and package target.
   - Recommended: TypeScript first if the later Codex skill and app layer will
     run in Node/TS.
   - Alternative: Python first if the immediate consumer is Python agents or
     notebooks.
2. Primary consumer.
   - Recommended: server-side agent/tooling SDK, not browser client SDK.
3. Public interface shape.
   - Recommended: workflow methods over raw table repositories.
4. Result philosophy.
   - Recommended: evidence-first nested objects with stable source IDs and
     nullable fields preserved.
5. Connection model.
   - Recommended: read-only pooled Postgres connection from env vars.
6. First vertical slice.
   - Recommended: bill search + bill detail/history because it exercises search,
     joins, null semantics, and evidence keys.
7. Whether to create a read-only database role.
   - Recommended: yes before any non-local deployment.
8. API layer timing.
   - Recommended: no hosted API until SDK workflows are stable. Build an API as
     a thin wrapper over the SDK later.
9. Data API usage.
   - Recommended: no for v1.
10. Semantic search or embeddings.
    - Recommended: no until measured pg_trgm recall failures are documented.

## Suggested New Repo Docs

Create these after grilling:

- `CONTEXT.md`: SDK glossary and boundaries.
- `docs/design/PRD.md`: user stories, public interfaces, result contracts, test
  strategy, out-of-scope.
- `docs/design/IA.md`: SDK workflows and information hierarchy, not UI screens.
- `docs/design/DECISIONS.md`: hard-to-reverse or surprising decisions.
- `docs/ops/DB-SCHEMA-INTROSPECTION.md`: generated by live Neon introspection.

## Out Of Scope For Congress-SDK v1

- Ingesting or mutating National Assembly source data.
- Restoring or migrating the database.
- Enabling Neon Data API as the product interface.
- Browser-side direct DB access.
- 법제처 statutes, decrees, administrative rules, interpretations, precedents,
  or Constitutional Court decisions.
- Social-problem web research.
- Stored policy topic modeling.
- Embeddings/vector search unless keyword retrieval fails in measured tests.
- Replacing DB NULLs with guessed values.

## Definition Of Done For SDK v1 Foundation

The foundation is ready when:

- The SDK can connect to Neon via env var without leaking secrets.
- It can introspect or validate the expected schema at startup/test time.
- It provides at least one high-value workflow method that returns evidence-rich
  nested data, not just raw rows.
- Tests run without the production DB by using a controlled test database or
  narrow integration fixture, while live smoke tests can run against Neon when
  credentials are present.
- All public results preserve source keys and null semantics.
- The PM can use the SDK output to trace a claim back to bill, meeting,
  utterance, vote, and member identifiers.
