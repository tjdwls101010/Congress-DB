"""회의 안건 텍스트 파싱 검증."""

from congress_db.ingest.agenda_parser import parse_agenda_item


def test_parse_agenda_item_extracts_order_and_bill_no() -> None:
    item = parse_agenda_item("1. 항공안전법 일부개정법률안(의안번호 2218348)")

    assert item.order_no == 1
    assert item.sub_name == "1. 항공안전법 일부개정법률안(의안번호 2218348)"
    assert item.bill_no == "2218348"


def test_parse_agenda_item_allows_non_bill_agenda() -> None:
    item = parse_agenda_item("국무총리 및 국무위원 출석요구의 건")

    assert item.order_no is None
    assert item.bill_no is None
