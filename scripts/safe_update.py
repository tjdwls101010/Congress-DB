#!/usr/bin/env python3
"""안전 Neon 업데이트 CLI.

백업 브랜치 → 증분 수집 → 무손상 검증 → (손상 시) 자동 복원.
CONGRESS_MAIN_URL / NEON_API_KEY / .neon 을 .env.local·repo에서 읽는다.
"""
from __future__ import annotations

import argparse

from congress_db.ops.safe_update import run_safe_update


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a non-destructive incremental update against Neon main."
    )
    parser.add_argument("--no-backup", action="store_true", help="백업 브랜치 생략 (비권장)")
    parser.add_argument("--keep-backup", action="store_true", help="무손상이어도 백업 브랜치 보존")
    parser.add_argument("--no-restore", action="store_true", help="손상 감지 시 자동 복원하지 않음")
    args = parser.parse_args()

    result = run_safe_update(
        make_backup=not args.no_backup,
        keep_backup=args.keep_backup,
        auto_restore=not args.no_restore,
    )
    raise SystemExit(0 if not result.failures else 1)


if __name__ == "__main__":
    main()
