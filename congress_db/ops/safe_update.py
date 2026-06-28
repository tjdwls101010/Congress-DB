"""안전 Neon 업데이트 — 어떤 상황에서도 기존 데이터를 손상하지 않는 증분 수집.

운영자(PM)가 `make safe-update`로 실행하는 단일 명령. 흐름:

1. main에서 **백업 브랜치**(즉시 copy-on-write 스냅샷)를 만든다 — 복원 보험.
2. 수집 전 **read-only fingerprint**를 뜬다.
3. 증분 수집(`run_ingest` auto→incremental)을 main에 실행한다.
4. 수집 후 fingerprint를 다시 뜨고 **무손상 diff**를 계산한다:
   기존 PK 삭제 / 자식 전멸 / non-null→null 회귀 / append 테이블 행 감소 / 회의 발언 전멸.
5. 손상 감지 시 → main을 백업 브랜치로 **자동 복원**(endpoint host 불변, 연결문자열 안깨짐).
   무손상 시 → 추가량 리포트 + 백업 브랜치 정리.

수집 엔진(`ingest_command`)은 자체적으로 비파괴(추가 전용·COALESCE·floor/cap 가드)지만,
이 래퍼는 그 위에 **탐지+즉시복원** 안전망을 둬 "어떤 상황에서도" 보장을 만든다.
백업/복원은 Neon 컨트롤플레인(NEON_API_KEY)을, 수집 타깃은 CONGRESS_MAIN_URL을 쓴다.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from ..core.progress import safe_print

NEON_API = "https://console.neon.tech/api/v2"

# 정확 PK 집합으로 삭제를 탐지할 소형 테이블 (대형 테이블은 count/부모 체크로 egress 절약)
_PK_TABLES = [
    "bills", "meetings", "members", "committees", "bill_final_outcomes",
    "bill_relations", "bill_source_aliases", "bill_lead_proposers",
]
# 순수 append 테이블: 행 수가 줄면 손상 (votes는 DELETE 경로가 없다)
_APPEND_ONLY = ["votes"]
# non-null → null 회귀를 볼 소형 소비자 테이블 (대형 본문은 IS NOT NULL bool만)
_NULL_TABLES = ["bills", "members", "meetings", "committees", "bill_final_outcomes"]
_NULL_EXCLUDE = {"members": {"poly_nm", "is_incumbent"}}  # 정당한 생애주기 변동 (CONTEXT)
# 자식 전멸/감소를 볼 (자식, 부모컬럼, 부모테이블)
_CHILD_PARENTS = [
    ("bill_lead_proposers", "bill_id", "bills"),
    ("bill_coproposers", "bill_id", "bills"),
    ("meeting_bills", "meeting_id", "meetings"),
]
_ALL_COUNT_TABLES = _PK_TABLES + _APPEND_ONLY + [
    "bill_coproposers", "meeting_bills", "utterances",
]


# ---------------------------------------------------------------- Neon 컨트롤플레인
def _neon(method: str, path: str, key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        NEON_API + path, data=data, method=method,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:  # pragma: no cover - 네트워크 경계
        raise RuntimeError(f"Neon API {method} {path} -> {e.code}: {e.read().decode()[:300]}") from None


def create_backup_branch(project: str, key: str, parent_branch_id: str, name: str) -> str:
    r = _neon("POST", f"/projects/{project}/branches", key,
              {"branch": {"name": name, "parent_id": parent_branch_id},
               "endpoints": [{"type": "read_write"}]})
    bid = r["branch"]["id"]
    for _ in range(60):
        b = _neon("GET", f"/projects/{project}/branches/{bid}", key)
        if b["branch"].get("current_state") == "ready":
            break
    return bid


def restore_branch(project: str, key: str, target_branch_id: str, source_branch_id: str) -> None:
    """target 브랜치를 source 브랜치의 head 상태로 되돌린다(endpoint host 불변)."""
    _neon("POST", f"/projects/{project}/branches/{target_branch_id}/restore", key,
          {"source_branch_id": source_branch_id})
    for _ in range(60):
        b = _neon("GET", f"/projects/{project}/branches/{target_branch_id}", key)
        if b["branch"].get("current_state") == "ready":
            break


def delete_branch(project: str, key: str, branch_id: str) -> None:
    _neon("DELETE", f"/projects/{project}/branches/{branch_id}", key)


# ------------------------------------------------------------- read-only fingerprint
def _pk_cols(cur: Any, table: str) -> list[str]:
    cur.execute(
        """SELECT a.attname FROM pg_index i
           JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
           WHERE i.indrelid=%s::regclass AND i.indisprimary ORDER BY a.attnum""",
        (table,))
    return [r[0] for r in cur.fetchall()]


def _columns(cur: Any, table: str) -> list[str]:
    cur.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position""",
        (table,))
    return [r[0] for r in cur.fetchall()]


def fingerprint(conn: psycopg.Connection) -> dict[str, Any]:
    """읽기 전용. 수집 전/후 각각 호출해 diff로 비교한다."""
    cur = conn.cursor()
    fp: dict[str, Any] = {"counts": {}, "pk": {}, "nullmap": {}, "child_parents": {}, "utt_by_meeting": {}}
    for t in _ALL_COUNT_TABLES:
        cur.execute(f"SELECT count(*) FROM {t}")
        fp["counts"][t] = cur.fetchone()[0]
    for t in _PK_TABLES:
        pkc = _pk_cols(cur, t)
        cur.execute(f"SELECT {', '.join(pkc)} FROM {t}")
        fp["pk"][t] = {tuple(r) for r in cur.fetchall()}
    for t in _NULL_TABLES:
        pkc = _pk_cols(cur, t)
        cols = [c for c in _columns(cur, t) if c not in pkc and c not in _NULL_EXCLUDE.get(t, set())]
        sel = ", ".join(pkc) + ", " + ", ".join(f"({c} IS NOT NULL)" for c in cols)
        cur.execute(f"SELECT {sel} FROM {t}")
        n = len(pkc)
        fp["nullmap"][t] = {"cols": cols, "rows": {tuple(r[:n]): r[n:] for r in cur.fetchall()}}
    for child, pcol, _parent in _CHILD_PARENTS:
        cur.execute(f"SELECT {pcol}, count(*) FROM {child} GROUP BY {pcol}")
        fp["child_parents"][child] = {r[0]: r[1] for r in cur.fetchall()}
    cur.execute("SELECT meeting_id, count(*) FROM utterances GROUP BY meeting_id")
    fp["utt_by_meeting"] = {r[0]: r[1] for r in cur.fetchall()}
    return fp


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """무손상 판정. FAIL이 비어 있으면 기존 데이터 무손상."""
    rep: dict[str, Any] = {"added": {}, "FAIL": [], "NOTE": []}
    for t in _ALL_COUNT_TABLES:
        rep["added"][t] = after["counts"][t] - before["counts"][t]
    # 1) 소형 테이블 기존 PK 삭제
    for t in _PK_TABLES:
        deleted = before["pk"][t] - after["pk"][t]
        if deleted:
            rep["FAIL"].append(f"{t}: {len(deleted)} pre-existing rows DELETED (sample={[list(x) for x in list(deleted)[:3]]})")
    # 2) append 전용 테이블 행 감소
    for t in _APPEND_ONLY:
        if after["counts"][t] < before["counts"][t]:
            rep["FAIL"].append(f"{t}: row count dropped {before['counts'][t]}→{after['counts'][t]} (append-only)")
    # 3) non-null → null 회귀
    for t in _NULL_TABLES:
        b, a = before["nullmap"][t], after["nullmap"][t]
        regs: dict[str, int] = {}
        for pk, bvec in b["rows"].items():
            avec = a["rows"].get(pk)
            if avec is None:
                continue
            for i, c in enumerate(b["cols"]):
                if bvec[i] and not avec[i]:
                    regs[c] = regs.get(c, 0) + 1
        if regs:
            rep["FAIL"].append(f"{t}: non-null→null regressions {regs}")
    # 4) 자식 전멸(부모 생존, 자식 0) / 감소(NOTE)
    for child, _pcol, _parent in _CHILD_PARENTS:
        b, a = before["child_parents"][child], after["child_parents"][child]
        wiped = [p for p, n in b.items() if n > 0 and a.get(p, 0) == 0]
        fewer = [p for p, n in b.items() if a.get(p, 0) and a[p] < n]
        if wiped:
            rep["FAIL"].append(f"{child}: {len(wiped)} parents lost ALL children (sample={wiped[:3]})")
        if fewer:
            rep["NOTE"].append(f"{child}: {len(fewer)} parents have fewer children (소스 변경/추가전용 정상 가능)")
    # 5) 살아남은 회의 발언 전멸(FAIL) / 감소(NOTE)
    emptied = decreased = 0
    for mid, bn in before["utt_by_meeting"].items():
        an = after["utt_by_meeting"].get(mid, 0)
        if an == 0:
            emptied += 1
        elif an < bn:
            decreased += 1
    if emptied:
        rep["FAIL"].append(f"utterances: {emptied} surviving meetings emptied")
    if decreased:
        rep["NOTE"].append(f"utterances: {decreased} meetings have fewer (재스크랩 정상 가능; floor 가드가 급감은 차단)")
    return rep


# ----------------------------------------------------------------- 오케스트레이션
@dataclass
class SafeUpdateResult:
    backup_branch_id: str | None
    ingest_status: str
    added: dict[str, int]
    failures: list[str] = field(default_factory=list)
    restored: bool = False


def _host(url: str) -> str:
    return url.split("@", 1)[1].split("/", 1)[0]


def _guard_production(url: str) -> str:
    h = _host(url)
    if any(x in h for x in ("localhost", "127.0.0.1", ":5432", ":5433")):
        raise SystemExit(f"[safe-update] ABORT: target looks local ({h}); set CONGRESS_MAIN_URL to Neon main")
    if "neon.tech" not in h:
        raise SystemExit(f"[safe-update] ABORT: target is not a Neon endpoint ({h})")
    return h


def run_safe_update(
    *,
    main_url: str | None = None,
    neon_key: str | None = None,
    project: str | None = None,
    main_branch_id: str = "br-plain-bird-ao3gndn3",
    make_backup: bool = True,
    auto_restore: bool = True,
    keep_backup: bool = False,
    now: datetime | None = None,
) -> SafeUpdateResult:
    main_url = main_url or os.environ.get("CONGRESS_MAIN_URL") or os.environ["DATABASE_URL"]
    neon_key = neon_key or os.environ.get("NEON_API_KEY")
    if project is None and Path(".neon").exists():
        project = json.loads(Path(".neon").read_text())["projectId"]
    host = _guard_production(main_url)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M")
    safe_print(f"[safe-update] target={host}", flush=True)

    backup_id: str | None = None
    if make_backup:
        if not (neon_key and project):
            raise SystemExit("[safe-update] 백업에 NEON_API_KEY + .neon project 필요 (또는 make_backup=False)")
        backup_id = create_backup_branch(project, neon_key, main_branch_id, f"pre-update-{stamp}")
        safe_print(f"[safe-update] backup branch={backup_id} (복원: restore main ← {backup_id})", flush=True)

    conn = psycopg.connect(main_url)
    conn.autocommit = True
    try:
        safe_print("[safe-update] fingerprint(before)…", flush=True)
        before = fingerprint(conn)

        os.environ["DATABASE_URL"] = main_url
        from ..ingest.ingest_command import run_ingest
        safe_print("[safe-update] incremental ingest…", flush=True)
        ingest = run_ingest(mode="auto")
        safe_print(f"[safe-update] ingest status={ingest.status} dead_letters={ingest.dead_letter_count}", flush=True)

        safe_print("[safe-update] fingerprint(after)…", flush=True)
        after = fingerprint(conn)
    finally:
        conn.close()

    rep = diff(before, after)
    added = {t: d for t, d in rep["added"].items() if d}
    safe_print(f"[safe-update] added rows: {added}", flush=True)
    for note in rep["NOTE"]:
        safe_print(f"[safe-update]   NOTE: {note}", flush=True)

    result = SafeUpdateResult(backup_branch_id=backup_id, ingest_status=ingest.status,
                              added=rep["added"], failures=list(rep["FAIL"]))
    if rep["FAIL"]:
        safe_print("[safe-update] ❌ DATA LOSS DETECTED:", flush=True)
        for f in rep["FAIL"]:
            safe_print(f"[safe-update]   - {f}", flush=True)
        if backup_id and auto_restore:
            safe_print(f"[safe-update] restoring main ← {backup_id} …", flush=True)
            restore_branch(project, neon_key, main_branch_id, backup_id)
            result.restored = True
            safe_print("[safe-update] ✅ main restored to pre-update snapshot. 기존 데이터 무손상.", flush=True)
        else:
            safe_print(f"[safe-update] 백업 브랜치 {backup_id} 에서 수동 복원하세요.", flush=True)
        return result

    safe_print("[safe-update] ✅ PASS — 기존 데이터 무손상, 신규만 추가됨.", flush=True)
    if backup_id and not keep_backup:
        delete_branch(project, neon_key, backup_id)
        safe_print(f"[safe-update] backup branch {backup_id} 삭제(무손상 확인).", flush=True)
    return result
