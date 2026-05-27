#!/usr/bin/env python3
"""session_groups 캘리브레이션 검증 CLI."""

from __future__ import annotations

from congress_db.validate_session_groups import validate_session_groups


def main() -> None:
    result = validate_session_groups()
    print(
        "Validated session groups: "
        f"meetings={result.total_meetings} "
        f"applicable={result.applicable_meetings} "
        f"meetings_with_groups={result.meetings_with_groups} "
        f"groups={result.group_count} "
        f"links={result.utterance_link_count} "
        f"integrity_errors="
        f"{result.skipped_with_groups + result.questioner_fk_missing + result.utterance_count_mismatch + result.total_chars_mismatch + result.respondents_format_invalid}"
    )


if __name__ == "__main__":
    main()
