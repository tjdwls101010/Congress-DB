"""발언-의원 매핑 품질 신호."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..ingest.scrape_minutes import normalize_speaker_name

MEMBER_SPEAKER_TITLE_ORDER = (
    "의원",
    "위원",
    "의장",
    "부의장",
    "의장대리",
    "위원장",
    "부위원장",
    "위원장대리",
    "소위원장",
    "소위원장대리",
)
MEMBER_SPEAKER_TITLES = frozenset(MEMBER_SPEAKER_TITLE_ORDER)


@dataclass(frozen=True)
class TitleMappingQuality:
    """직함별 발언-의원 매핑 품질."""

    speaker_title: str
    total_utterances: int
    mapped_utterances: int
    unmapped_utterances: int
    ambiguous_name_unmapped: int
    mapping_rate_pct: float | None

    def as_report_row(self) -> dict[str, object]:
        return {
            "speaker_title": self.speaker_title,
            "total_utterances": self.total_utterances,
            "mapped_utterances": self.mapped_utterances,
            "unmapped_utterances": self.unmapped_utterances,
            "ambiguous_name_unmapped": self.ambiguous_name_unmapped,
            "mapping_rate_pct": _format_rate(self.mapping_rate_pct),
        }


@dataclass(frozen=True)
class UnmappedSpeakerQuality:
    """미매핑 의원형 화자 분류."""

    speaker_name: str
    speaker_title: str
    utterances: int
    member_name_matches: int
    classification: str

    def as_report_row(self) -> dict[str, object]:
        return {
            "speaker_name": self.speaker_name,
            "speaker_title": self.speaker_title,
            "utterances": self.utterances,
            "member_name_matches": self.member_name_matches,
            "classification": self.classification,
        }


@dataclass(frozen=True)
class MemberUtteranceMappingQuality:
    """의원형 직함 발언의 의원 FK 매핑 품질."""

    total_utterances: int
    mapped_utterances: int
    unmapped_utterances: int
    ambiguous_name_unmapped: int
    safe_mapping_candidate_unmapped: int
    no_member_reference_unmapped: int
    mapping_rate_pct: float | None
    actionable_mapping_rate_pct: float | None
    by_title: tuple[TitleMappingQuality, ...]
    unmapped_speakers: tuple[UnmappedSpeakerQuality, ...]


def load_member_utterance_mapping_quality(
    cur: object,
    *,
    sample_limit: int = 25,
) -> MemberUtteranceMappingQuality:
    """현재 DB에서 의원형 직함 발언의 member FK 매핑 품질을 읽는다."""
    title_rows = _load_title_rows(cur)
    member_name_index = _load_member_name_index(cur)
    unmapped_speakers = _load_unmapped_speakers(cur, member_name_index)

    ambiguous_by_title = Counter[str]()
    for row in unmapped_speakers:
        if row.classification == "ambiguous_name":
            ambiguous_by_title[row.speaker_title] += row.utterances

    title_quality = tuple(
        TitleMappingQuality(
            speaker_title=title,
            total_utterances=title_rows.get(title, {}).get("total_utterances", 0),
            mapped_utterances=title_rows.get(title, {}).get("mapped_utterances", 0),
            unmapped_utterances=title_rows.get(title, {}).get("unmapped_utterances", 0),
            ambiguous_name_unmapped=ambiguous_by_title[title],
            mapping_rate_pct=_rate_pct(
                title_rows.get(title, {}).get("mapped_utterances", 0),
                title_rows.get(title, {}).get("total_utterances", 0),
            ),
        )
        for title in MEMBER_SPEAKER_TITLE_ORDER
    )

    total = sum(row.total_utterances for row in title_quality)
    mapped = sum(row.mapped_utterances for row in title_quality)
    unmapped = sum(row.unmapped_utterances for row in title_quality)
    ambiguous = sum(row.utterances for row in unmapped_speakers if row.classification == "ambiguous_name")
    safe_candidates = sum(
        row.utterances for row in unmapped_speakers if row.classification == "safe_mapping_candidate"
    )
    no_member_reference = sum(
        row.utterances for row in unmapped_speakers if row.classification == "no_member_reference"
    )
    actionable_denominator = total - ambiguous
    return MemberUtteranceMappingQuality(
        total_utterances=total,
        mapped_utterances=mapped,
        unmapped_utterances=unmapped,
        ambiguous_name_unmapped=ambiguous,
        safe_mapping_candidate_unmapped=safe_candidates,
        no_member_reference_unmapped=no_member_reference,
        mapping_rate_pct=_rate_pct(mapped, total),
        actionable_mapping_rate_pct=_rate_pct(mapped, actionable_denominator),
        by_title=title_quality,
        unmapped_speakers=tuple(unmapped_speakers[:sample_limit]),
    )


def _load_title_rows(cur: object) -> dict[str, dict[str, int]]:
    cur.execute(
        """
        SELECT
            speaker_title,
            COUNT(*)::int AS total_utterances,
            COUNT(*) FILTER (WHERE speaker_mona_cd IS NOT NULL)::int AS mapped_utterances,
            COUNT(*) FILTER (WHERE speaker_mona_cd IS NULL)::int AS unmapped_utterances
        FROM utterances
        WHERE speaker_title = ANY(%s)
        GROUP BY speaker_title
        """,
        (list(MEMBER_SPEAKER_TITLE_ORDER),),
    )
    rows: dict[str, dict[str, int]] = {}
    for speaker_title, total, mapped, unmapped in cur.fetchall():
        rows[str(speaker_title)] = {
            "total_utterances": int(total),
            "mapped_utterances": int(mapped),
            "unmapped_utterances": int(unmapped),
        }
    return rows


def _load_member_name_index(cur: object) -> dict[str, set[str]]:
    cur.execute("SELECT hg_nm, mona_cd FROM members")
    names: dict[str, set[str]] = {}
    for hg_nm, mona_cd in cur.fetchall():
        names.setdefault(normalize_speaker_name(hg_nm), set()).add(str(mona_cd))
    return names


def _load_unmapped_speakers(
    cur: object,
    member_name_index: Mapping[str, set[str]],
) -> tuple[UnmappedSpeakerQuality, ...]:
    cur.execute(
        """
        SELECT speaker_name, speaker_title, COUNT(*)::int AS utterances
        FROM utterances
        WHERE speaker_title = ANY(%s)
          AND speaker_mona_cd IS NULL
        GROUP BY speaker_name, speaker_title
        ORDER BY utterances DESC, speaker_name, speaker_title
        """,
        (list(MEMBER_SPEAKER_TITLE_ORDER),),
    )
    rows = []
    for speaker_name, speaker_title, utterances in cur.fetchall():
        match_count = len(member_name_index.get(normalize_speaker_name(speaker_name), set()))
        rows.append(
            UnmappedSpeakerQuality(
                speaker_name=str(speaker_name),
                speaker_title=str(speaker_title),
                utterances=int(utterances),
                member_name_matches=match_count,
                classification=_classify_match_count(match_count),
            )
        )
    return tuple(rows)


def _classify_match_count(match_count: int) -> str:
    if match_count == 0:
        return "no_member_reference"
    if match_count == 1:
        return "safe_mapping_candidate"
    return "ambiguous_name"


def _rate_pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 2)


def _format_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"
