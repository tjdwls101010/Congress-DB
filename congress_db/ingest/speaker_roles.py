"""발언 역할 정규화.

분류 규칙의 single source of truth다. 증분 utterance 적재와 기존 행 백필은
반드시 `classify_speaker_role()`을 통해 같은 역할 enum을 산출한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from ..core.db import get_conn

SpeakerRole = Literal[
    "의원",
    "국무위원(장관)",
    "차관",
    "증인",
    "참고인",
    "전문위원",
    "기타",
]

SPEAKER_ROLES: tuple[SpeakerRole, ...] = (
    "의원",
    "국무위원(장관)",
    "차관",
    "증인",
    "참고인",
    "전문위원",
    "기타",
)

LEGISLATOR_TITLES = frozenset(
    {
        "의원",
        "위원",
        "위원장",
        "위원장대리",
        "소위원장",
        "소위원장대리",
        "의장",
        "의장대리",
        "부의장",
        "부위원장",
        "간사",
    }
)
PROFESSIONAL_STAFF_TITLES = frozenset({"전문위원", "수석전문위원"})
OTHER_MARKERS = frozenset({"후보자", "직무대행", "직무대리", "권한대행"})
JUDICIAL_OR_LEGISLATIVE_OFFICE_PREFIXES = (
    "법원행정처",
    "헌법재판소",
    "중앙선거관리위원회",
    "국회",
)
EXECUTIVE_DEPUTY_PREFIXES = (
    "국무조정실",
    "국가안보실",
    "국가정보원",
    "대통령경호처",
    "국세청",
    "관세청",
    "조달청",
    "통계청",
    "병무청",
    "방위사업청",
    "경찰청",
    "소방청",
    "농촌진흥청",
    "산림청",
    "특허청",
    "기상청",
    "질병관리청",
    "해양경찰청",
    "행정중심복합도시건설청",
    "새만금개발청",
    "우주항공청",
    "재외동포청",
    "국가유산청",
    "인사혁신처",
    "법제처",
    "식품의약품안전처",
    "국가데이터처",
    "지식재산처",
)

_ROLE_VALUES_SQL = ", ".join(f"'{role}'" for role in SPEAKER_ROLES)


@dataclass(frozen=True)
class SpeakerTitleRoleSummary:
    speaker_title: str
    speaker_role: SpeakerRole
    n_utterances: int
    n_no_mona: int
    n_mona: int


@dataclass(frozen=True)
class SpeakerRoleNormalizationResult:
    utterance_count: int
    updated_utterance_count: int
    null_speaker_role_count: int
    role_distribution: Mapping[str, int]
    high_frequency_other_titles: tuple[SpeakerTitleRoleSummary, ...]


def classify_speaker_role(
    speaker_title: str | None,
    speaker_mona_cd: str | None = None,
) -> SpeakerRole:
    """원천 직함과 의원 FK로 발언 역할 enum을 산출한다."""
    if speaker_mona_cd is not None and str(speaker_mona_cd).strip():
        return "의원"

    title = _normalize_title(speaker_title)
    if title in LEGISLATOR_TITLES:
        return "의원"
    if not title or title.startswith("(전)") or any(marker in title for marker in OTHER_MARKERS):
        return "기타"
    if title == "증인":
        return "증인"
    if title == "참고인":
        return "참고인"
    if title in PROFESSIONAL_STAFF_TITLES:
        return "전문위원"
    if title == "국무총리" or title.endswith("장관"):
        return "국무위원(장관)"
    if title.endswith("차관"):
        return "차관"
    if _is_executive_deputy_title(title):
        return "차관"
    return "기타"


def normalize_speaker_roles(*, other_threshold: int = 500) -> SpeakerRoleNormalizationResult:
    """기존 utterances의 speaker_role을 채우고 최종 제약을 적용한다."""
    with get_conn() as conn:
        title_rows = _load_title_rows(conn)
        role_keys = _build_role_keys(title_rows)
        title_summaries = _build_title_summaries(title_rows)

        _upsert_title_role_map(conn, title_summaries)
        _drop_role_index(conn)
        updated = _backfill_utterance_roles(conn, role_keys)
        _ensure_no_null_roles(conn)
        _apply_role_constraints(conn)
        _create_role_index(conn)
        role_distribution = _load_role_distribution(conn)
        high_frequency_other_titles = tuple(
            row
            for row in title_summaries
            if row.speaker_role == "기타" and row.n_utterances >= other_threshold
        )
        null_count = _load_null_role_count(conn)
        utterance_count = sum(role_distribution.values())
        conn.commit()

    return SpeakerRoleNormalizationResult(
        utterance_count=utterance_count,
        updated_utterance_count=updated,
        null_speaker_role_count=null_count,
        role_distribution=role_distribution,
        high_frequency_other_titles=high_frequency_other_titles,
    )


def _normalize_title(speaker_title: str | None) -> str:
    if speaker_title is None:
        return ""
    return "".join(str(speaker_title).split())


def _is_executive_deputy_title(title: str) -> bool:
    if not title.endswith("차장"):
        return False
    if title.startswith(JUDICIAL_OR_LEGISLATIVE_OFFICE_PREFIXES):
        return False
    return title.startswith(EXECUTIVE_DEPUTY_PREFIXES)


def _load_title_rows(conn: object) -> list[dict[str, object]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                speaker_title,
                COUNT(*)::bigint AS n_utterances,
                COUNT(*) FILTER (WHERE speaker_mona_cd IS NULL)::bigint AS n_no_mona,
                COUNT(*) FILTER (WHERE speaker_mona_cd IS NOT NULL)::bigint AS n_mona,
                BOOL_OR(speaker_mona_cd IS NOT NULL) AS has_mona,
                BOOL_OR(speaker_mona_cd IS NULL) AS has_no_mona
            FROM utterances
            GROUP BY speaker_title
            ORDER BY n_utterances DESC, speaker_title
            """
        )
        return [
            {
                "speaker_title": str(row[0]),
                "n_utterances": int(row[1]),
                "n_no_mona": int(row[2]),
                "n_mona": int(row[3]),
                "has_mona": bool(row[4]),
                "has_no_mona": bool(row[5]),
            }
            for row in cur.fetchall()
        ]


def _build_role_keys(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    keys: list[dict[str, object]] = []
    for row in rows:
        title = str(row["speaker_title"])
        if bool(row["has_mona"]):
            keys.append(
                {
                    "speaker_title": title,
                    "has_mona": True,
                    "speaker_role": classify_speaker_role(title, "mapped"),
                }
            )
        if bool(row["has_no_mona"]):
            keys.append(
                {
                    "speaker_title": title,
                    "has_mona": False,
                    "speaker_role": classify_speaker_role(title, None),
                }
            )
    return keys


def _build_title_summaries(rows: list[dict[str, object]]) -> tuple[SpeakerTitleRoleSummary, ...]:
    summaries = [
        SpeakerTitleRoleSummary(
            speaker_title=str(row["speaker_title"]),
            speaker_role=classify_speaker_role(str(row["speaker_title"]), None),
            n_utterances=int(row["n_utterances"]),
            n_no_mona=int(row["n_no_mona"]),
            n_mona=int(row["n_mona"]),
        )
        for row in rows
    ]
    return tuple(sorted(summaries, key=lambda row: (-row.n_utterances, row.speaker_title)))


def _upsert_title_role_map(
    conn: object,
    title_summaries: tuple[SpeakerTitleRoleSummary, ...],
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO speaker_title_role_map (
                speaker_title, speaker_role, n_utterances, n_no_mona, n_mona, classified_at
            )
            VALUES (
                %(speaker_title)s, %(speaker_role)s, %(n_utterances)s,
                %(n_no_mona)s, %(n_mona)s, now()
            )
            ON CONFLICT (speaker_title) DO UPDATE SET
                speaker_role = EXCLUDED.speaker_role,
                n_utterances = EXCLUDED.n_utterances,
                n_no_mona = EXCLUDED.n_no_mona,
                n_mona = EXCLUDED.n_mona,
                classified_at = now()
            """,
            [
                {
                    "speaker_title": row.speaker_title,
                    "speaker_role": row.speaker_role,
                    "n_utterances": row.n_utterances,
                    "n_no_mona": row.n_no_mona,
                    "n_mona": row.n_mona,
                }
                for row in title_summaries
            ],
        )


def _backfill_utterance_roles(conn: object, role_keys: list[dict[str, object]]) -> int:
    title_role_keys = [row for row in role_keys if row["has_mona"] is False]
    mapped_member_role = classify_speaker_role(None, "mapped")
    updated = 0
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE utterances
            SET speaker_role = %s
            WHERE speaker_mona_cd IS NOT NULL
              AND speaker_role IS DISTINCT FROM %s
            """,
            (mapped_member_role, mapped_member_role),
        )
        updated += int(cur.rowcount)

        if not title_role_keys:
            return updated

        cur.execute(
            """
            CREATE TEMP TABLE tmp_speaker_role_keys (
                speaker_title TEXT PRIMARY KEY,
                speaker_role TEXT NOT NULL
            ) ON COMMIT DROP
            """
        )
        cur.executemany(
            """
            INSERT INTO tmp_speaker_role_keys (speaker_title, speaker_role)
            VALUES (%(speaker_title)s, %(speaker_role)s)
            """,
            title_role_keys,
        )
        cur.execute("ANALYZE tmp_speaker_role_keys")
        cur.execute("SET LOCAL enable_nestloop = off")
        cur.execute(
            """
            UPDATE utterances AS u
            SET speaker_role = k.speaker_role
            FROM tmp_speaker_role_keys AS k
            WHERE u.speaker_title = k.speaker_title
              AND u.speaker_mona_cd IS NULL
              AND u.speaker_role IS DISTINCT FROM k.speaker_role
            """
        )
        updated += int(cur.rowcount)
        return updated


def _ensure_no_null_roles(conn: object) -> None:
    null_count = _load_null_role_count(conn)
    if null_count:
        raise RuntimeError(f"speaker_role backfill left NULL rows: {null_count}")


def _apply_role_constraints(conn: object) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            ALTER TABLE utterances
                DROP CONSTRAINT IF EXISTS utterances_speaker_role_check
            """
        )
        cur.execute(
            f"""
            ALTER TABLE utterances
                ADD CONSTRAINT utterances_speaker_role_check
                CHECK (speaker_role IN ({_ROLE_VALUES_SQL}))
                NOT VALID
            """
        )
        cur.execute(
            """
            ALTER TABLE utterances
                VALIDATE CONSTRAINT utterances_speaker_role_check
            """
        )
        cur.execute("ALTER TABLE utterances ALTER COLUMN speaker_role SET NOT NULL")


def _drop_role_index(conn: object) -> None:
    with conn.cursor() as cur:
        cur.execute("DROP INDEX IF EXISTS idx_utterances_role_meeting_sequence")


def _create_role_index(conn: object) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_utterances_role_meeting_sequence
                ON utterances (speaker_role, meeting_id, sequence)
            """
        )


def _load_role_distribution(conn: object) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT speaker_role, COUNT(*)::bigint
            FROM utterances
            GROUP BY speaker_role
            ORDER BY speaker_role
            """
        )
        return {str(role): int(count) for role, count in cur.fetchall()}


def _load_null_role_count(conn: object) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*)::bigint FROM utterances WHERE speaker_role IS NULL")
        return int(cur.fetchone()[0])
