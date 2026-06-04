# Use one ingest entrypoint

PMs and operators should run one ingest command, not manually compose member, bill, vote, meeting, utterance, and session-group stages. The command decides whether the run is initial backfill or incremental sync, retries unresolved dead letters first, avoids duplicate rows through upserts and scoped recalculation, and records the decision path in `ingest_runs` so later sessions can audit what happened.
