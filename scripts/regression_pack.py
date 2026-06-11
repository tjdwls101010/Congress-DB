#!/usr/bin/env python3
"""4-scenario retrieval regression pack CLI."""

from __future__ import annotations

from congress_db.ops.regression_pack import run_regression_pack


def main() -> None:
    try:
        report = run_regression_pack()
    except KeyError as exc:
        if exc.args == ("CONGRESS_RO_URL",):
            raise SystemExit("CONGRESS_RO_URL is required for regression-pack") from exc
        raise

    status = "PASS" if report.passed else "FAIL"
    print(
        "Generated regression pack: "
        f"status={status} "
        f"scenarios={len(report.scenarios)} "
        f"markdown=docs/ops/REGRESSION-PACK.md "
        f"json=docs/ops/REGRESSION-PACK.json"
    )
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
