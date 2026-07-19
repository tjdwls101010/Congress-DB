"""Representative direct-SQL consumer queries.

이 테스트는 Python helper가 아니라 public schema/view만 사용한다. 목적은 직접 SQL 소비자가
법안 생애주기, 원안→대안 계보, 위원회별 처리 현황을 자연스럽게 조립할 수 있음을 고정하는 것이다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from congress_db.core.db import get_conn

TEST_COMMITTEE_ID = "TEST_SQL_CMT"
TEST_MEMBER_1 = "TEST_SQL_M1"
TEST_MEMBER_2 = "TEST_SQL_M2"
TEST_ORIGINAL_BILL = "TEST_SQL_ORIGINAL"
TEST_ALTERNATIVE_BILL = "TEST_SQL_ALTERNATIVE"
TEST_SOURCE_ALT_ID = "TEST_SQL_SOURCE_ALT"


def setup_function() -> None:
    _delete_fixture()


def teardown_function() -> None:
    _delete_fixture()


def _delete_fixture() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM votes WHERE bill_id = ANY(%s)",
            ([TEST_ORIGINAL_BILL, TEST_ALTERNATIVE_BILL],),
        )
        cur.execute(
            "DELETE FROM bill_lead_proposers WHERE bill_id = ANY(%s)",
            ([TEST_ORIGINAL_BILL, TEST_ALTERNATIVE_BILL],),
        )
        cur.execute(
            "DELETE FROM bill_coproposers WHERE bill_id = ANY(%s)",
            ([TEST_ORIGINAL_BILL, TEST_ALTERNATIVE_BILL],),
        )
        cur.execute(
            "DELETE FROM bill_final_outcomes WHERE bill_no = ANY(%s)",
            (["2999101", "2999102"],),
        )
        cur.execute(
            """
            DELETE FROM bill_relations
            WHERE absorbed_bill_id = ANY(%s)
               OR alternative_bill_id = ANY(%s)
            """,
            ([TEST_ORIGINAL_BILL, TEST_ALTERNATIVE_BILL], [TEST_SOURCE_ALT_ID]),
        )
        cur.execute(
            """
            DELETE FROM bill_source_aliases
            WHERE source_bill_id = %s OR canonical_bill_id = ANY(%s)
            """,
            (TEST_SOURCE_ALT_ID, [TEST_ORIGINAL_BILL, TEST_ALTERNATIVE_BILL]),
        )
        cur.execute(
            "DELETE FROM bills WHERE bill_id = ANY(%s)",
            ([TEST_ORIGINAL_BILL, TEST_ALTERNATIVE_BILL],),
        )
        cur.execute("DELETE FROM members WHERE mona_cd = ANY(%s)", ([TEST_MEMBER_1, TEST_MEMBER_2],))
        cur.execute("DELETE FROM committees WHERE committee_id = %s", (TEST_COMMITTEE_ID,))
        conn.commit()


def _seed_fixture() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO committees (committee_id, committee_name)
            VALUES (%s, '직접SQL테스트위원회')
            """,
            (TEST_COMMITTEE_ID,),
        )
        cur.executemany(
            """
            INSERT INTO members (mona_cd, hg_nm, poly_nm, is_incumbent)
            VALUES (%(mona_cd)s, %(hg_nm)s, %(poly_nm)s, true)
            """,
            [
                {"mona_cd": TEST_MEMBER_1, "hg_nm": "직접일", "poly_nm": "테스트당"},
                {"mona_cd": TEST_MEMBER_2, "hg_nm": "직접이", "poly_nm": "검증당"},
            ],
        )
        cur.executemany(
            """
            INSERT INTO bills (
                bill_id, bill_no, bill_name, propose_dt, committee_id,
                proc_result, proc_dt, cmt_proc_dt, cmt_proc_result, summary
            )
            VALUES (
                %(bill_id)s, %(bill_no)s, %(bill_name)s, %(propose_dt)s,
                %(committee_id)s, %(proc_result)s, %(proc_dt)s, %(cmt_proc_dt)s,
                %(cmt_proc_result)s, %(summary)s
            )
            """,
            [
                {
                    "bill_id": TEST_ORIGINAL_BILL,
                    "bill_no": "2999101",
                    "bill_name": "직접 SQL 원안 법률안",
                    "propose_dt": date(2026, 1, 10),
                    "committee_id": TEST_COMMITTEE_ID,
                    "proc_result": "대안반영폐기",
                    "proc_dt": date(2026, 2, 20),
                    "cmt_proc_dt": date(2026, 2, 10),
                    "cmt_proc_result": "대안반영폐기",
                    "summary": "직접 SQL 계약 테스트 원안",
                },
                {
                    "bill_id": TEST_ALTERNATIVE_BILL,
                    "bill_no": "2999102",
                    "bill_name": "직접 SQL 대안 법률안",
                    "propose_dt": date(2026, 2, 11),
                    "committee_id": TEST_COMMITTEE_ID,
                    "proc_result": "원안가결",
                    "proc_dt": date(2026, 3, 1),
                    "cmt_proc_dt": date(2026, 2, 21),
                    "cmt_proc_result": "대안가결",
                    "summary": "직접 SQL 계약 테스트 대안",
                },
            ],
        )
        cur.execute(
            """
            INSERT INTO bill_relations (absorbed_bill_id, alternative_bill_id, relation_type)
            VALUES (%s, %s, '대안반영')
            """,
            (TEST_ORIGINAL_BILL, TEST_SOURCE_ALT_ID),
        )
        cur.execute(
            """
            INSERT INTO bill_source_aliases (
                source, source_bill_id, bill_no, canonical_bill_id
            )
            VALUES ('likms_billdetail', %s, '2999102', %s)
            """,
            (TEST_SOURCE_ALT_ID, TEST_ALTERNATIVE_BILL),
        )
        cur.executemany(
            """
            INSERT INTO bill_lead_proposers (bill_id, mona_cd, order_no)
            VALUES (%(bill_id)s, %(mona_cd)s, %(order_no)s)
            """,
            [
                {"bill_id": TEST_ORIGINAL_BILL, "mona_cd": TEST_MEMBER_1, "order_no": 1},
                {"bill_id": TEST_ALTERNATIVE_BILL, "mona_cd": TEST_MEMBER_2, "order_no": 1},
            ],
        )
        cur.execute(
            """
            INSERT INTO bill_coproposers (bill_id, mona_cd, order_no)
            VALUES (%s, %s, 1)
            """,
            (TEST_ORIGINAL_BILL, TEST_MEMBER_2),
        )
        cur.execute(
            """
            INSERT INTO bill_final_outcomes (
                bill_no, plenary_dt, govt_transfer_dt, promulgation_dt, prom_no, prom_law_nm
            )
            VALUES ('2999102', '2026-03-01', '2026-03-05', '2026-03-20', '20999',
                    '직접 SQL 대안 법률')
            """
        )
        cur.executemany(
            """
            INSERT INTO votes (bill_id, mona_cd, vote_date, result_vote_mod, poly_nm_at_vote)
            VALUES (%(bill_id)s, %(mona_cd)s, %(vote_date)s, %(result_vote_mod)s, %(poly_nm)s)
            """,
            [
                {
                    "bill_id": TEST_ALTERNATIVE_BILL,
                    "mona_cd": TEST_MEMBER_1,
                    "vote_date": "2026-03-01 10:00:00+09",
                    "result_vote_mod": "찬성",
                    "poly_nm": "테스트당",
                },
                {
                    "bill_id": TEST_ALTERNATIVE_BILL,
                    "mona_cd": TEST_MEMBER_2,
                    "vote_date": "2026-03-01 10:00:00+09",
                    "result_vote_mod": "반대",
                    "poly_nm": "검증당",
                },
            ],
        )
        conn.commit()


def _fetch_one(sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        assert row is not None
        return dict(zip([col.name for col in cur.description], row, strict=True))


def test_bill_lifecycle_query_uses_public_direct_sql_surface() -> None:
    _seed_fixture()

    row = _fetch_one(
        """
        WITH target AS (
            SELECT bill_id
            FROM bills
            WHERE bill_no = %s
        )
        SELECT
            b.bill_no,
            b.bill_name,
            c.committee_name,
            b.propose_dt,
            b.cmt_proc_dt,
            b.cmt_proc_result,
            b.proc_result,
            b.proc_dt,
            o.plenary_dt,
            o.govt_transfer_dt,
            o.promulgation_dt,
            o.prom_no,
            o.prom_law_nm,
            (
                SELECT jsonb_agg(m.hg_nm ORDER BY lp.order_no)
                FROM bill_lead_proposers lp
                JOIN members m USING (mona_cd)
                WHERE lp.bill_id = b.bill_id
            ) AS lead_proposers,
            (
                SELECT jsonb_object_agg(result_vote_mod, vote_count)
                FROM (
                    SELECT result_vote_mod, count(*) AS vote_count
                    FROM votes
                    WHERE bill_id = b.bill_id
                    GROUP BY result_vote_mod
                ) v
            ) AS vote_summary
        FROM target t
        JOIN bills b ON b.bill_id = t.bill_id
        LEFT JOIN committees c ON c.committee_id = b.committee_id
        LEFT JOIN bill_final_outcomes o ON o.bill_no = b.bill_no
        """,
        ("2999102",),
    )

    assert row["committee_name"] == "직접SQL테스트위원회"
    assert row["proc_result"] == "원안가결"
    assert row["promulgation_dt"] == date(2026, 3, 20)
    assert row["prom_no"] == "20999"
    assert row["prom_law_nm"] == "직접 SQL 대안 법률"
    assert row["lead_proposers"] == ["직접이"]
    assert row["vote_summary"] == {"반대": 1, "찬성": 1}


def test_bill_lineage_view_hides_alias_resolution_from_consumers() -> None:
    _seed_fixture()

    row = _fetch_one(
        """
        SELECT absorbed_bill_no, alternative_bill_no, relation_type
        FROM bill_lineage
        WHERE absorbed_bill_no = %s
        """,
        ("2999101",),
    )

    assert row == {
        "absorbed_bill_no": "2999101",
        "alternative_bill_no": "2999102",
        "relation_type": "대안반영",
    }


def test_committee_period_status_query_is_plain_sql() -> None:
    _seed_fixture()

    row = _fetch_one(
        """
        SELECT c.committee_name, b.proc_result, count(*)::int AS bill_count
        FROM bills b
        JOIN committees c ON c.committee_id = b.committee_id
        WHERE b.committee_id = %s
          AND b.proc_dt >= %s
          AND b.proc_dt < %s
        GROUP BY c.committee_name, b.proc_result
        HAVING b.proc_result = '원안가결'
        """,
        (TEST_COMMITTEE_ID, date(2026, 3, 1), date(2026, 4, 1)),
    )

    assert row == {
        "committee_name": "직접SQL테스트위원회",
        "proc_result": "원안가결",
        "bill_count": 1,
    }
