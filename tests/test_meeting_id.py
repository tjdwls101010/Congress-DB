"""회의록 통합 식별자 파싱 검증."""

import pytest

from congress_db.meeting_id import extract_mnts_id


def test_extract_mnts_id_from_pdf_url_id_param() -> None:
    url = "https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do?id=56654"

    assert extract_mnts_id(url) == 56654


def test_extract_mnts_id_accepts_confer_num_string() -> None:
    assert extract_mnts_id("56654") == 56654


def test_extract_mnts_id_rejects_missing_id() -> None:
    with pytest.raises(ValueError):
        extract_mnts_id("https://record.assembly.go.kr/assembly/viewer/minutes/download/pdf.do")
