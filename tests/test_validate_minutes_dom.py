"""회의록 DOM 검증 리포트 검증."""

from congress_db.ingest.scrape_minutes import MinutesDomProfile
from congress_db.ops.validate_minutes_dom import (
    DomValidationResult,
    DomValidationRow,
    MeetingSample,
    render_dom_validation_report,
)


def test_render_dom_validation_report_summarizes_types(tmp_path) -> None:
    sample = MeetingSample(
        mnts_id=920001,
        meeting_type="상임위",
        conf_date="2026-05-20",
        title="테스트 회의",
        sample_layer="recent",
    )
    result = DomValidationResult(
        rows=(
            DomValidationRow(
                sample=sample,
                profile=MinutesDomProfile(
                    mnts_id=920001,
                    title="테스트 회의",
                    has_minutes_body=True,
                    speaker_count=3,
                    data_name_count=3,
                    data_pos_count=3,
                    talk_txt_count=3,
                    spk_sub_speaker_count=2,
                    utterance_count=3,
                    first_speaker_class="item0 speaker spk_mem",
                ),
            ),
        )
    )
    output = tmp_path / "MINUTES-DOM-VALIDATION.md"

    render_dom_validation_report(result, output)

    text = output.read_text()
    assert "Checked meetings: 1" in text
    assert "| 상임위 | 1 | 0 | 0 | 3 | 3 |" in text
    assert "`item0 speaker spk_mem`" in text
