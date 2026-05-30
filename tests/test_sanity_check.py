"""Slice 10 sanity check report behavior."""

from congress_db.sanity_check import (
    FtsDecision,
    SanityCheckResult,
    SanitySection,
    _S3_MEETING_STREAMS_SQL,
    render_sanity_report,
)


def test_render_sanity_report_shows_all_scenarios_and_fts_decision(tmp_path) -> None:
    output = tmp_path / "SANITY-CHECK.md"
    result = SanityCheckResult(
        row_counts={"members": 298, "utterances": 586766},
        sections=(
            SanitySection(
                key="S1",
                title="의원 통합 조회",
                query_goal="임의 의원 5명",
                rows=({"의원": "홍길동", "발언수": 10},),
            ),
            SanitySection(
                key="S7",
                title="정당별 표결 패턴",
                query_goal="최근 표결 월",
                rows=(),
                note="No rows returned.",
            ),
        ),
        fts_decision=FtsDecision(
            selected="pg_trgm",
            alternatives=("Postgres simple tsvector", "PGroonga"),
            rationale=("Works in the local Postgres image and Supabase.",),
            migration_path="db/migrations/001_search_indexes.sql",
        ),
    )

    render_sanity_report(result, output)

    text = output.read_text()
    assert "# Integrated Sanity Check" in text
    assert "- members: 298" in text
    assert "## S1. 의원 통합 조회" in text
    assert "| 의원 | 발언수 |" in text
    assert "## S7. 정당별 표결 패턴" in text
    assert "No rows returned." in text
    assert "- Selected: `pg_trgm`" in text
    assert "- Migration: `db/migrations/001_search_indexes.sql`" in text


def test_render_sanity_report_escapes_markdown_table_cells(tmp_path) -> None:
    output = tmp_path / "SANITY-CHECK.md"
    result = SanityCheckResult(
        row_counts={},
        sections=(
            SanitySection(
                key="S4",
                title="키워드 검색",
                query_goal="pipe and newline escaping",
                rows=({"content": "A | B\nC"},),
            ),
        ),
        fts_decision=FtsDecision(
            selected="pg_trgm",
            alternatives=(),
            rationale=(),
            migration_path="db/migrations/001_search_indexes.sql",
        ),
    )

    render_sanity_report(result, output)

    assert "A \\| B C" in output.read_text()


def test_s3_meeting_streams_query_preaggregates_relation_counts() -> None:
    assert "COUNT(DISTINCT" not in _S3_MEETING_STREAMS_SQL
    assert "agenda_items" not in _S3_MEETING_STREAMS_SQL
    assert "bill_counts AS" in _S3_MEETING_STREAMS_SQL
    assert "utterance_counts AS" in _S3_MEETING_STREAMS_SQL
    assert "group_counts AS" in _S3_MEETING_STREAMS_SQL
