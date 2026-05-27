# Use pg_trgm for first Korean keyword search

For the first Supabase-bound search slice, Korean keyword search uses `pg_trgm` GIN indexes on bill names, bill summaries, and utterance content. PGroonga is the stronger multilingual search option and is supported by Supabase, but adopting it now would require changing the local Postgres runtime before we have proved that substring keyword search is insufficient.
