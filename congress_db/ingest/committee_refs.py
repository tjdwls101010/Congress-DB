"""Helpers for preserving bill-side committee identity before bill upserts."""

from __future__ import annotations

from typing import Any

from psycopg import Connection

from ..core.db import execute_many


_INSERT_COMMITTEES_SQL = """
    INSERT INTO committees (committee_id, committee_name)
    VALUES (%(committee_id)s, %(committee_name)s)
    ON CONFLICT (committee_id) DO NOTHING
"""


def normalize_committee_rows(
    rows: list[dict[str, Any]],
    *,
    id_field: str,
    name_field: str,
) -> list[dict[str, str]]:
    """Return unique committee id/name pairs from source rows."""
    names_by_id: dict[str, str] = {}
    ids_by_name: dict[str, str] = {}
    for row in rows:
        committee_id = _blank_to_none(row.get(id_field))
        committee_name = _blank_to_none(row.get(name_field))
        if not committee_id and not committee_name:
            continue
        if not committee_id or not committee_name:
            raise ValueError(
                "committee source row has partial id/name pair: "
                f"{id_field}={committee_id!r} {name_field}={committee_name!r}"
            )
        existing_name = names_by_id.get(committee_id)
        if existing_name is not None and existing_name != committee_name:
            raise ValueError(
                "committee source rows map one id to multiple names: "
                f"{committee_id} -> {existing_name!r}, {committee_name!r}"
            )
        existing_id = ids_by_name.get(committee_name)
        if existing_id is not None and existing_id != committee_id:
            raise ValueError(
                "committee source rows map one name to multiple ids: "
                f"{committee_name!r} -> {existing_id}, {committee_id}"
            )
        names_by_id[committee_id] = committee_name
        ids_by_name[committee_name] = committee_id
    return [
        {"committee_id": committee_id, "committee_name": committee_name}
        for committee_id, committee_name in sorted(names_by_id.items())
    ]


def ensure_committee_refs(conn: Connection, rows: list[dict[str, str]]) -> int:
    """Insert committee rows after checking conflicts with existing canonical names."""
    if not rows:
        return 0
    committee_ids = [row["committee_id"] for row in rows]
    committee_names = [row["committee_name"] for row in rows]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT committee_id, committee_name
            FROM committees
            WHERE committee_id = ANY(%s)
               OR committee_name = ANY(%s)
            """,
            (committee_ids, committee_names),
        )
        existing = [(str(row[0]), str(row[1])) for row in cur.fetchall()]

    incoming_name_by_id = {row["committee_id"]: row["committee_name"] for row in rows}
    incoming_id_by_name = {row["committee_name"]: row["committee_id"] for row in rows}
    for existing_id, existing_name in existing:
        incoming_name = incoming_name_by_id.get(existing_id)
        if incoming_name is not None and incoming_name != existing_name:
            raise ValueError(
                "committee id already has a different canonical name: "
                f"{existing_id} existing={existing_name!r} incoming={incoming_name!r}"
            )
        incoming_id = incoming_id_by_name.get(existing_name)
        if incoming_id is not None and incoming_id != existing_id:
            raise ValueError(
                "committee name already has a different canonical id: "
                f"{existing_name!r} existing={existing_id} incoming={incoming_id}"
            )
    return execute_many(conn, _INSERT_COMMITTEES_SQL, rows)


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
