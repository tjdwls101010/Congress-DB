"""회의 안건(`SUB_NAME`) 파싱."""

from __future__ import annotations

import re
from dataclasses import dataclass


_ORDER_RE = re.compile(r"^\s*(\d+)\s*[.)]\s*")
_BILL_NO_RE = re.compile(r"의안번호\s*[:：]?\s*(\d{7})")


@dataclass(frozen=True)
class AgendaItemDraft:
    """DB 적재 전 안건 파싱 결과."""

    order_no: int | None
    sub_name: str
    bill_no: str | None


def parse_agenda_item(value: str) -> AgendaItemDraft:
    """안건 원문에서 안건 번호와 의안번호를 추출한다."""
    sub_name = value.strip()
    order_match = _ORDER_RE.search(sub_name)
    bill_match = _BILL_NO_RE.search(sub_name)
    return AgendaItemDraft(
        order_no=int(order_match.group(1)) if order_match else None,
        sub_name=sub_name,
        bill_no=bill_match.group(1) if bill_match else None,
    )
