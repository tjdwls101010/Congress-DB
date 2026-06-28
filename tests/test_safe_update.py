"""안전 업데이트 무손상 fingerprint/diff 로직 검증.

Neon 컨트롤플레인(백업/복원)은 라이브 API라 여기서 테스트하지 않고, 손상 탐지의
핵심인 fingerprint·diff 순수 로직을 단위 검증한다.
"""

from __future__ import annotations

import copy

from congress_db.core.db import get_conn
from congress_db.ops.safe_update import (
    _ALL_COUNT_TABLES,
    _CHILD_PARENTS,
    _NULL_TABLES,
    _PK_TABLES,
    diff,
    fingerprint,
)


def _baseline() -> dict:
    """무손상(자기 자신 비교 시 FAIL 없음) 최소 fingerprint."""
    fp: dict = {"counts": {}, "pk": {}, "nullmap": {}, "child_parents": {}, "utt_by_meeting": {}}
    for t in _ALL_COUNT_TABLES:
        fp["counts"][t] = 10
    for t in _PK_TABLES:
        fp["pk"][t] = {(1,), (2,), (3,)}
    for t in _NULL_TABLES:
        fp["nullmap"][t] = {"cols": ["proc_result"], "rows": {(1,): (True,), (2,): (True,)}}
    for child, _pcol, _parent in _CHILD_PARENTS:
        fp["child_parents"][child] = {100: 2, 200: 3}
    fp["utt_by_meeting"] = {500: 40, 501: 60}
    return fp


def test_diff_clean_when_only_additions() -> None:
    before = _baseline()
    after = copy.deepcopy(before)
    for t in _ALL_COUNT_TABLES:
        after["counts"][t] += 5  # 추가만
    for t in _PK_TABLES:
        after["pk"][t] = before["pk"][t] | {(4,)}  # 새 PK 추가
    rep = diff(before, after)
    assert rep["FAIL"] == [], rep["FAIL"]


def test_diff_detects_deleted_pk() -> None:
    before = _baseline()
    after = copy.deepcopy(before)
    after["pk"]["bills"] = {(1,), (2,)}  # (3,) 삭제
    rep = diff(before, after)
    assert any("bills" in f and "DELETED" in f for f in rep["FAIL"]), rep["FAIL"]


def test_diff_detects_null_regression() -> None:
    before = _baseline()
    after = copy.deepcopy(before)
    after["nullmap"]["bills"]["rows"][(1,)] = (False,)  # proc_result 채움→NULL
    rep = diff(before, after)
    assert any("regression" in f for f in rep["FAIL"]), rep["FAIL"]


def test_diff_detects_child_wipeout() -> None:
    before = _baseline()
    after = copy.deepcopy(before)
    after["child_parents"]["bill_lead_proposers"] = {100: 0, 200: 3}  # 부모 100 자식 전멸
    rep = diff(before, after)
    assert any("lost ALL children" in f for f in rep["FAIL"]), rep["FAIL"]


def test_diff_detects_append_only_decrease() -> None:
    before = _baseline()
    after = copy.deepcopy(before)
    after["counts"]["votes"] -= 1  # append 전용 감소
    rep = diff(before, after)
    assert any("votes" in f and "append-only" in f for f in rep["FAIL"]), rep["FAIL"]


def test_diff_detects_emptied_meeting() -> None:
    before = _baseline()
    after = copy.deepcopy(before)
    after["utt_by_meeting"] = {500: 0, 501: 60}  # 회의 500 발언 전멸
    rep = diff(before, after)
    assert any("emptied" in f for f in rep["FAIL"]), rep["FAIL"]


def test_fingerprint_runs_readonly_against_db() -> None:
    with get_conn() as conn:
        conn.autocommit = True
        fp = fingerprint(conn)
    assert "bills" in fp["counts"]
    assert "bills" in fp["pk"]
    assert "votes" in fp["counts"]
    assert isinstance(fp["utt_by_meeting"], dict)
