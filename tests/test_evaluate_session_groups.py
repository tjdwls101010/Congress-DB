"""session_group 정확도 검증 리포트 검증."""

from congress_db.evaluate_session_groups import (
    EvalMeeting,
    evaluate_label_rows,
    render_eval_report,
)


def test_evaluate_label_rows_calculates_precision_and_recall() -> None:
    result = evaluate_label_rows(
        [
            {"label": "correct"},
            {"label": "correct"},
            {"label": "incorrect"},
            {"label": "missing"},
            {"label": ""},
        ]
    )

    assert result.correct_count == 2
    assert result.incorrect_count == 1
    assert result.missing_count == 1
    assert result.pending_count == 1
    assert result.precision == 2 / 3
    assert result.recall == 2 / 3
    assert result.is_complete is False


def test_render_eval_report_keeps_pending_state_visible(tmp_path) -> None:
    result = evaluate_label_rows([{"label": ""}])
    output = tmp_path / "SESSION-GROUP-EVAL.md"

    render_eval_report(
        result=result,
        meetings=[
            EvalMeeting(
                meeting_id=1,
                meeting_type="국정감사",
                conf_date="2026-05-20",
                title="테스트 회의",
                group_count=7,
            )
        ],
        labels_path=tmp_path / "labels.csv",
        output_path=output,
    )

    text = output.read_text()
    assert "Labeled review status: pending labeled review" in text
    assert "Precision: pending" in text
    assert "Types without sampled meetings:" in text
    assert "| 국정감사 | 1 | 2026-05-20 | 7 | 테스트 회의 |" in text
