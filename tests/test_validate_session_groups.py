"""session_groups 검증 리포트 렌더링 검증."""

from decimal import Decimal

from congress_db.validate_session_groups import (
    SessionGroupTypeMetric,
    SessionGroupValidationResult,
    render_session_group_report,
)


def test_render_session_group_report_summarizes_generation_rate(tmp_path) -> None:
    result = SessionGroupValidationResult(
        total_meetings=10,
        skipped_meetings=2,
        applicable_meetings=8,
        meetings_with_groups=6,
        group_count=42,
        utterance_link_count=300,
        skipped_with_groups=0,
        questioner_fk_missing=0,
        utterance_count_mismatch=0,
        total_chars_mismatch=0,
        respondents_format_invalid=0,
        respondent_empty_groups=3,
        groups_with_50_plus_utterances=4,
        groups_with_100_plus_utterances=1,
        max_group_utterance_count=128,
        type_metrics=(
            SessionGroupTypeMetric(
                meeting_type="상임위",
                meetings=8,
                skipped=0,
                applicable=8,
                applicable_with_groups=6,
                groups=42,
                applicable_success_pct=Decimal("75.0"),
            ),
        ),
    )
    output = tmp_path / "SESSION-GROUPS-CALIBRATION.md"

    render_session_group_report(result, output)

    text = output.read_text()
    assert "Applicable meetings with groups: 6 (75.0%)" in text
    assert "Groups with 100+ utterances: 1" in text
    assert "Largest group utterance count: 128" in text
    assert "Invalid respondents JSONB: 0" in text
    assert "| 상임위 | 8 | 0 | 8 | 6 | 42 | 75.0% |" in text
