"""발언-의원 매핑 품질 신호 검증."""

from __future__ import annotations

from typing import Any

from congress_db.utterance_mapping_quality import load_member_utterance_mapping_quality


class FakeCursor:
    def __init__(self) -> None:
        self.calls = 0
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, _sql: str, _params: object | None = None) -> None:
        self.calls += 1
        if self.calls == 1:
            self._rows = [
                ("의장", 1, 1, 0),
                ("위원장", 1, 0, 1),
                ("소위원장대리", 1, 0, 1),
                ("부의장", 1, 0, 1),
            ]
        elif self.calls == 2:
            self._rows = [
                ("동명이", "TEST_A"),
                ("동명이", "TEST_B"),
                ("안전일", "TEST_C"),
                ("매핑일", "TEST_D"),
            ]
        elif self.calls == 3:
            self._rows = [
                ("동명이", "위원장", 1),
                ("안전일", "소위원장대리", 1),
                ("무참조", "부의장", 1),
            ]
        else:
            self._rows = []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


def test_member_utterance_mapping_quality_uses_all_member_titles() -> None:
    quality = load_member_utterance_mapping_quality(FakeCursor())

    assert quality.total_utterances == 4
    assert quality.mapped_utterances == 1
    assert quality.unmapped_utterances == 3
    assert quality.ambiguous_name_unmapped == 1
    assert quality.safe_mapping_candidate_unmapped == 1
    assert quality.no_member_reference_unmapped == 1
    assert quality.mapping_rate_pct == 25.0
    assert quality.actionable_mapping_rate_pct == 33.33
    assert {row.classification for row in quality.unmapped_speakers} == {
        "ambiguous_name",
        "safe_mapping_candidate",
        "no_member_reference",
    }
