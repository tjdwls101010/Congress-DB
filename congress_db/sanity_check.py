"""통합 sanity check 리포트 생성."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .db import get_conn

DEFAULT_SANITY_REPORT = Path("docs/SANITY-CHECK.md")
DEFAULT_KEYWORD = "전세사기"
DEFAULT_RESPONDENT_TITLE_PATTERN = "%기획재정부장관%"
ROW_COUNT_TABLES = (
    "members",
    "bills",
    "bill_lead_proposers",
    "bill_coproposers",
    "votes",
    "meetings",
    "meeting_bills",
    "utterances",
    "session_groups",
)

_S3_MEETING_STREAMS_SQL = """
    WITH bill_counts AS (
        SELECT meeting_id, COUNT(*) AS bill_count
        FROM meeting_bills
        GROUP BY meeting_id
    ), utterance_counts AS (
        SELECT meeting_id, COUNT(*) AS utterance_count
        FROM utterances
        GROUP BY meeting_id
    ), group_counts AS (
        SELECT meeting_id, COUNT(*) AS group_count
        FROM session_groups
        GROUP BY meeting_id
    )
    SELECT
        m.mnts_id AS "회의ID",
        m.meeting_type AS "유형",
        m.conf_date AS "일자",
        left(m.title, 90) AS "회의명",
        COALESCE(bc.bill_count, 0) AS "연결법안",
        COALESCE(uc.utterance_count, 0) AS "발언",
        COALESCE(gc.group_count, 0) AS "Q&A그룹",
        first_u.speaker_name AS "첫발언자",
        left(first_u.content, 120) AS "첫발언"
    FROM meetings m
    LEFT JOIN bill_counts bc ON bc.meeting_id = m.mnts_id
    LEFT JOIN utterance_counts uc ON uc.meeting_id = m.mnts_id
    LEFT JOIN group_counts gc ON gc.meeting_id = m.mnts_id
    LEFT JOIN LATERAL (
        SELECT speaker_name, content
        FROM utterances u
        WHERE u.meeting_id = m.mnts_id
        ORDER BY sequence
        LIMIT 1
    ) first_u ON true
    WHERE COALESCE(uc.utterance_count, 0) > 0
    ORDER BY m.conf_date DESC, m.mnts_id DESC
    LIMIT %s
    """


@dataclass(frozen=True)
class SanitySection:
    """S1~S7 검증용 결과 표."""

    key: str
    title: str
    query_goal: str
    rows: Sequence[Mapping[str, object]]
    note: str = ""


@dataclass(frozen=True)
class FtsDecision:
    """한국어 검색 인덱스 결정."""

    selected: str
    alternatives: Sequence[str]
    rationale: Sequence[str]
    migration_path: str


@dataclass(frozen=True)
class QualitySignal:
    """PM이 sanity check 때 봐야 할 데이터 품질 신호."""

    metric: str
    value: int
    interpretation: str


@dataclass(frozen=True)
class SanityCheckResult:
    """통합 검증 리포트 입력값."""

    row_counts: Mapping[str, int]
    sections: Sequence[SanitySection]
    fts_decision: FtsDecision
    quality_signals: Sequence[QualitySignal] = ()


def run_sanity_check(
    *,
    output_path: Path = DEFAULT_SANITY_REPORT,
    sample_size: int = 5,
    keyword: str = DEFAULT_KEYWORD,
    respondent_title_pattern: str = DEFAULT_RESPONDENT_TITLE_PATTERN,
) -> SanityCheckResult:
    """S1~S7 쿼리를 실행하고 Markdown 리포트를 저장한다."""
    with get_conn() as conn, conn.cursor() as cur:
        result = SanityCheckResult(
            row_counts=_load_row_counts(cur),
            sections=(
                _load_s1_member_cards(cur, sample_size),
                _load_s2_bill_process(cur, sample_size),
                _load_s3_meeting_streams(cur, sample_size),
                _load_s4_bill_keyword(cur, sample_size, keyword),
                _load_s4_utterance_keyword(cur, sample_size, keyword),
                _load_s5_committee_activity(cur, committee_count=2, per_committee=5),
                _load_s6_respondent_search(cur, sample_size, respondent_title_pattern),
                _load_s7_party_vote_pattern(cur),
            ),
            fts_decision=default_fts_decision(),
            quality_signals=_load_quality_signals(cur),
        )
    render_sanity_report(result, output_path)
    return result


def default_fts_decision() -> FtsDecision:
    """현재 프로젝트의 한국어 검색 인덱스 선택."""
    return FtsDecision(
        selected="pg_trgm",
        alternatives=("Postgres simple tsvector", "PGroonga"),
        rationale=(
            "Postgres simple tsvector is easy to index, but Korean keyword search "
            "needs reliable substring matching across particles and spacing.",
            "PGroonga is the stronger multilingual search engine, but it is not "
            "available in the current local Postgres image and would add "
            "environment churn before the first hosted Postgres migration.",
            "pg_trgm works in the current Postgres 16 container, is available on "
            "Neon, and gives the API/SDK a practical first keyword-search "
            "path for bills and utterances.",
        ),
        migration_path="db/migrations/001_search_indexes.sql",
    )


def render_sanity_report(result: SanityCheckResult, output_path: Path) -> None:
    """검증 결과를 Markdown 파일로 저장한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_render_markdown(result))


def _load_row_counts(cur: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in ROW_COUNT_TABLES:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        counts[table] = cur.fetchone()[0]
    return counts


def _load_s1_member_cards(cur: object, sample_size: int) -> SanitySection:
    cur.execute(
        """
        WITH lead_counts AS (
            SELECT mona_cd, COUNT(*) AS cnt
            FROM bill_lead_proposers
            GROUP BY mona_cd
        ), co_counts AS (
            SELECT mona_cd, COUNT(*) AS cnt
            FROM bill_coproposers
            GROUP BY mona_cd
        ), vote_counts AS (
            SELECT mona_cd, COUNT(*) AS cnt
            FROM votes
            GROUP BY mona_cd
        ), utterance_counts AS (
            SELECT speaker_mona_cd AS mona_cd, COUNT(*) AS cnt
            FROM utterances
            WHERE speaker_mona_cd IS NOT NULL
            GROUP BY speaker_mona_cd
        ), group_counts AS (
            SELECT questioner_mona_cd AS mona_cd, COUNT(*) AS cnt
            FROM session_groups
            GROUP BY questioner_mona_cd
        )
        SELECT
            m.hg_nm AS "의원",
            m.poly_nm AS "정당",
            m.mona_cd AS "mona_cd",
            COALESCE(l.cnt, 0) AS "대표발의",
            COALESCE(c.cnt, 0) AS "공동발의",
            COALESCE(v.cnt, 0) AS "표결",
            COALESCE(u.cnt, 0) AS "발언",
            COALESCE(g.cnt, 0) AS "Q&A그룹"
        FROM members m
        LEFT JOIN lead_counts l ON l.mona_cd = m.mona_cd
        LEFT JOIN co_counts c ON c.mona_cd = m.mona_cd
        LEFT JOIN vote_counts v ON v.mona_cd = m.mona_cd
        LEFT JOIN utterance_counts u ON u.mona_cd = m.mona_cd
        LEFT JOIN group_counts g ON g.mona_cd = m.mona_cd
        ORDER BY COALESCE(u.cnt, 0) DESC, COALESCE(l.cnt, 0) DESC, m.hg_nm
        LIMIT %s
        """,
        (sample_size,),
    )
    return SanitySection(
        key="S1",
        title="의원 통합 조회",
        query_goal="발언 수가 많은 임의 의원 5명의 발의/표결/발언/Q&A 그룹 연결 상태",
        rows=_fetch_dicts(cur),
    )


def _load_s2_bill_process(cur: object, sample_size: int) -> SanitySection:
    cur.execute(
        """
        WITH lead_counts AS (
            SELECT bill_id, COUNT(*) AS cnt
            FROM bill_lead_proposers
            GROUP BY bill_id
        ), co_counts AS (
            SELECT bill_id, COUNT(*) AS cnt
            FROM bill_coproposers
            GROUP BY bill_id
        ), vote_summary AS (
            SELECT bill_id, SUM(cnt) AS vote_count,
                   jsonb_object_agg(result_vote_mod, cnt ORDER BY result_vote_mod) AS summary
            FROM (
                SELECT bill_id, result_vote_mod, COUNT(*) AS cnt
                FROM votes
                GROUP BY bill_id, result_vote_mod
            ) v
            GROUP BY bill_id
        )
        SELECT
            b.bill_no AS "의안번호",
            left(b.bill_name, 90) AS "법안명",
            b.propose_dt AS "제안일",
            b.committee AS "소관위",
            b.proc_result AS "처리결과",
            COALESCE(l.cnt, 0) AS "대표발의자수",
            COALESCE(c.cnt, 0) AS "공동발의자수",
            COALESCE(v.vote_count, 0) AS "표결수",
            COALESCE(v.summary::text, '{}') AS "표결요약"
        FROM bills b
        LEFT JOIN lead_counts l ON l.bill_id = b.bill_id
        LEFT JOIN co_counts c ON c.bill_id = b.bill_id
        LEFT JOIN vote_summary v ON v.bill_id = b.bill_id
        ORDER BY COALESCE(v.vote_count, 0) DESC, b.propose_dt DESC NULLS LAST, b.bill_no
        LIMIT %s
        """,
        (sample_size,),
    )
    return SanitySection(
        key="S2",
        title="법안 처리과정 추적",
        query_goal="표결 또는 최근 처리 데이터가 있는 법안 5개의 발의자/처리/표결 연결 상태",
        rows=_fetch_dicts(cur),
    )


def _load_s3_meeting_streams(cur: object, sample_size: int) -> SanitySection:
    cur.execute(_S3_MEETING_STREAMS_SQL, (sample_size,))
    return SanitySection(
        key="S3",
        title="회의 본문 + 법안 + 발언 stream",
        query_goal="최근 회의 5개의 연결법안/발언/Q&A 그룹 연결 상태",
        rows=_fetch_dicts(cur),
    )


def _load_s4_bill_keyword(cur: object, sample_size: int, keyword: str) -> SanitySection:
    pattern = f"%{keyword}%"
    cur.execute(
        """
        SELECT
            bill_no AS "의안번호",
            left(bill_name, 90) AS "법안명",
            propose_dt AS "제안일",
            committee AS "소관위",
            proc_result AS "처리결과"
        FROM bills
        WHERE bill_name ILIKE %s
           OR summary ILIKE %s
        ORDER BY propose_dt DESC NULLS LAST, bill_no
        LIMIT %s
        """,
        (pattern, pattern, sample_size),
    )
    return SanitySection(
        key="S4a",
        title="법안 키워드 검색",
        query_goal=f"`{keyword}`가 법안명 또는 주요내용에 포함된 법안",
        rows=_fetch_dicts(cur),
        note="`pg_trgm` GIN 인덱스가 ILIKE 기반 한국어 키워드 검색을 지원한다.",
    )


def _load_s4_utterance_keyword(cur: object, sample_size: int, keyword: str) -> SanitySection:
    pattern = f"%{keyword}%"
    cur.execute(
        """
        SELECT
            m.conf_date AS "일자",
            m.meeting_type AS "회의유형",
            left(m.title, 90) AS "회의명",
            u.sequence AS "순번",
            u.speaker_name AS "화자",
            u.speaker_title AS "직함",
            CASE WHEN u.session_group_id IS NULL THEN 'ungrouped'
                 ELSE u.session_group_id::text
            END AS "Q&A그룹",
            left(regexp_replace(u.content, E'[\\n\\r\\t]+', ' ', 'g'), 180) AS "발췌"
        FROM utterances u
        JOIN meetings m ON m.mnts_id = u.meeting_id
        WHERE u.content ILIKE %s
        ORDER BY m.conf_date DESC, u.meeting_id, u.sequence
        LIMIT %s
        """,
        (pattern, sample_size),
    )
    return SanitySection(
        key="S4b",
        title="발언 키워드 검색",
        query_goal=f"`{keyword}`가 발언 본문에 포함된 utterance와 회의 문맥",
        rows=_fetch_dicts(cur),
        note="`session_group_id`가 없는 hit는 API/SDK에서 같은 회의의 sequence window로 보완한다.",
    )


def _load_s5_committee_activity(
    cur: object,
    *,
    committee_count: int,
    per_committee: int,
) -> SanitySection:
    cur.execute(
        """
        WITH selected_committees AS (
            SELECT mt.comm_name, COUNT(*) AS utterance_count
            FROM utterances u
            JOIN meetings mt ON mt.mnts_id = u.meeting_id
            WHERE mt.comm_name IS NOT NULL
              AND u.speaker_mona_cd IS NOT NULL
            GROUP BY mt.comm_name
            ORDER BY COUNT(*) DESC, mt.comm_name
            LIMIT %s
        ), speaker_counts AS (
            SELECT
                sc.comm_name,
                mem.hg_nm,
                mem.poly_nm,
                COUNT(*) AS utterance_count,
                SUM(char_length(u.content)) AS total_chars
            FROM selected_committees sc
            JOIN meetings mt ON mt.comm_name = sc.comm_name
            JOIN utterances u ON u.meeting_id = mt.mnts_id
            JOIN members mem ON mem.mona_cd = u.speaker_mona_cd
            GROUP BY sc.comm_name, mem.mona_cd, mem.hg_nm, mem.poly_nm
        ), ranked AS (
            SELECT *,
                   row_number() OVER (
                       PARTITION BY comm_name
                       ORDER BY utterance_count DESC, total_chars DESC, hg_nm
                   ) AS rn
            FROM speaker_counts
        )
        SELECT
            comm_name AS "위원회",
            rn AS "순위",
            hg_nm AS "의원",
            poly_nm AS "정당",
            utterance_count AS "발언수",
            total_chars AS "총글자수"
        FROM ranked
        WHERE rn <= %s
        ORDER BY comm_name, rn
        """,
        (committee_count, per_committee),
    )
    return SanitySection(
        key="S5",
        title="위원회 단위 활동",
        query_goal="발언량이 많은 위원회 2개의 의원별 발언량 top 5",
        rows=_fetch_dicts(cur),
    )


def _load_s6_respondent_search(
    cur: object,
    sample_size: int,
    respondent_title_pattern: str,
) -> SanitySection:
    cur.execute(
        """
        WITH target_title AS (
            SELECT item->>'title' AS title, COUNT(*) AS cnt
            FROM session_groups sg,
                 jsonb_array_elements(sg.respondents) AS item
            WHERE item->>'title' ILIKE %s
            GROUP BY item->>'title'
            ORDER BY COUNT(*) DESC, item->>'title'
            LIMIT 1
        )
        SELECT
            t.title AS "답변자직함",
            m.conf_date AS "일자",
            left(m.title, 90) AS "회의명",
            mem.hg_nm AS "질의자",
            sg.utterance_count AS "발언수",
            sg.seq_start AS "시작",
            sg.seq_end AS "끝",
            sg.respondents::text AS "답변자JSON"
        FROM target_title t
        JOIN session_groups sg
          ON sg.respondents @> jsonb_build_array(jsonb_build_object('title', t.title))
        JOIN meetings m ON m.mnts_id = sg.meeting_id
        JOIN members mem ON mem.mona_cd = sg.questioner_mona_cd
        ORDER BY m.conf_date DESC, sg.id DESC
        LIMIT %s
        """,
        (respondent_title_pattern, sample_size),
    )
    return SanitySection(
        key="S6",
        title="Q&A 단위 검색",
        query_goal=f"`{respondent_title_pattern}`에 맞는 정부 부처 답변자의 JSONB containment 검색",
        rows=_fetch_dicts(cur),
        note="응답자 title은 실제 데이터에서 가장 많이 등장한 정확한 title을 고른 뒤 JSONB @>로 조회한다.",
    )


def _load_s7_party_vote_pattern(cur: object) -> SanitySection:
    cur.execute(
        """
        WITH latest_month AS (
            SELECT date_trunc('month', MAX(vote_date)) AS month_start
            FROM votes
        )
        SELECT
            to_char(lm.month_start, 'YYYY-MM') AS "표결월",
            COALESCE(v.poly_nm_at_vote, '정당미상') AS "정당",
            v.result_vote_mod AS "표결",
            COUNT(*) AS "표수"
        FROM votes v
        CROSS JOIN latest_month lm
        WHERE lm.month_start IS NOT NULL
          AND v.vote_date >= lm.month_start
          AND v.vote_date < lm.month_start + INTERVAL '1 month'
        GROUP BY lm.month_start, COALESCE(v.poly_nm_at_vote, '정당미상'), v.result_vote_mod
        ORDER BY "정당", "표결"
        """
    )
    return SanitySection(
        key="S7",
        title="정당별/시점별 표결 패턴",
        query_goal="가장 최근 표결 월의 정당별 찬반/기권/불참 분포",
        rows=_fetch_dicts(cur),
    )


def _load_quality_signals(cur: object) -> tuple[QualitySignal, ...]:
    queries = (
        (
            "members_missing_party",
            "SELECT COUNT(*) FROM members WHERE poly_nm IS NULL OR poly_nm = ''",
            "members stub 또는 의원 인적사항 API 누락 가능성. 의원 카드 완성도에 직접 영향이 있다.",
        ),
        (
            "bills_missing_propose_dt",
            "SELECT COUNT(*) FROM bills WHERE propose_dt IS NULL",
            "표결 endpoint에서 들어온 대안/처리 법안의 원천 metadata gap. full backfill 이후에도 accepted gap으로 추적한다.",
        ),
        (
            "bills_missing_summary",
            "SELECT COUNT(*) FROM bills WHERE summary IS NULL OR summary = ''",
            "법안명 검색은 가능하지만 summary 기반 recall에는 영향. 원천 summary 부재/미제공 후보로 추적한다.",
        ),
        (
            "member_titled_utterances_unmapped",
            """
            SELECT COUNT(*)
            FROM utterances
            WHERE speaker_title IN ('위원', '의원')
              AND speaker_mona_cd IS NULL
            """,
            "의원 발언인데 member FK가 없는 후보. 이름 중복/직함 파싱 문제일 수 있다.",
        ),
    )
    signals: list[QualitySignal] = []
    for metric, sql, interpretation in queries:
        cur.execute(sql)
        signals.append(
            QualitySignal(
                metric=metric,
                value=cur.fetchone()[0],
                interpretation=interpretation,
            )
        )
    return tuple(signals)


def _fetch_dicts(cur: object) -> tuple[dict[str, object], ...]:
    columns = [description.name for description in cur.description]
    return tuple(dict(zip(columns, row, strict=True)) for row in cur.fetchall())


def _render_markdown(result: SanityCheckResult) -> str:
    lines = [
        "# Integrated Sanity Check",
        "",
        "This report runs the IA S1-S7 query paths against the current local backfill load.",
        "It is a review artifact: code checks that the paths execute, and the PM can scan the rows for domain plausibility.",
        "",
        "## Dataset Row Counts",
        "",
    ]
    for table, count in result.row_counts.items():
        lines.append(f"- {table}: {count}")

    lines.extend(
        [
            "",
            "## Korean Search Decision",
            "",
            f"- Selected: `{result.fts_decision.selected}`",
            f"- Migration: `{result.fts_decision.migration_path}`",
            f"- Alternatives considered: {', '.join(result.fts_decision.alternatives) or '-'}",
        ]
    )
    for item in result.fts_decision.rationale:
        lines.append(f"- Rationale: {item}")

    if result.quality_signals:
        lines.extend(
            [
                "",
                "## Data Quality Signals",
                "",
                "| Metric | Value | Interpretation |",
                "| --- | ---: | --- |",
            ]
        )
        for signal in result.quality_signals:
            lines.append(
                f"| `{signal.metric}` | {signal.value} | "
                f"{_escape_cell(signal.interpretation)} |"
            )

    lines.extend(["", "## Scenario Results", ""])
    for section in result.sections:
        lines.extend(
            [
                f"## {section.key}. {section.title}",
                "",
                f"**Goal:** {section.query_goal}",
                "",
            ]
        )
        if section.note:
            lines.extend([section.note, ""])
        lines.extend(_render_table(section.rows))
        lines.append("")

    return "\n".join(lines)


def _render_table(rows: Sequence[Mapping[str, object]]) -> list[str]:
    if not rows:
        return ["_No rows returned._"]

    headers = list(rows[0].keys())
    lines = [
        "| " + " | ".join(_escape_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(_escape_cell(row.get(header, "")) for header in headers)
            + " |"
        )
    return lines


def _escape_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = " ".join(text.split())
    if len(text) > 220:
        text = text[:217].rstrip() + "..."
    return text.replace("|", "\\|")
