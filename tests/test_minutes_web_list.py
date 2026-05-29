"""국회회의록 웹 목록 크롤러 검증."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from congress_db.minutes_web_list import collect_minutes_web_list, crawl_minutes_web_list, web_meeting_to_row


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.get_class_ids: list[int] = []
        self.post_endpoints: list[str] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        class_id = int(parse_qs(urlparse(url).query)["class_id_sch"][0])
        self.get_class_ids.append(class_id)
        if class_id in {1, 4}:
            return _Response(_entry_with_session(class_id))
        return _Response(_entry_with_committee(class_id, _committee_name(class_id)))

    def post(self, url: str, **kwargs: object) -> _Response:
        endpoint = url.rsplit("/", 1)[-1]
        data = kwargs["data"]
        assert isinstance(data, dict)
        self.post_endpoints.append(endpoint)
        class_id = int(data["class_id_sch"])
        if endpoint == "sess.do":
            return _Response(_final_row(class_id, class_id * 100 + 1))
        if endpoint == "sessCmit.do":
            if class_id == 5:
                return _Response(_year_child(class_id))
            return _Response(_session_child(class_id))
        if endpoint == "cmit.do":
            return _Response(_final_row(class_id, class_id * 100 + 2))
        raise AssertionError(endpoint)


def test_crawl_minutes_web_list_expands_all_classes_and_ignores_non_view_links() -> None:
    session = _FakeSession()

    result = collect_minutes_web_list(session=session)
    meetings = result.meetings

    by_id = {meeting.mnts_id: meeting for meeting in meetings}
    assert session.get_class_ids == [1, 2, 4, 3, 5, 6]
    assert set(session.post_endpoints) == {"sess.do", "sessCmit.do", "cmit.do"}
    assert set(by_id) == {101, 202, 302, 401, 502, 602}

    plenary = by_id[101]
    assert plenary.meeting_type == "본회의"
    assert plenary.conf_date.isoformat() == "2026-05-08"
    assert plenary.session_no == 435
    assert plenary.degree == "제2차"
    assert plenary.is_temporary is True
    assert plenary.detail_url.endswith("/assembly/viewer/minutes/xml.do?id=101&type=view")

    subcommittee = by_id[202]
    assert subcommittee.meeting_type == "소위원회"
    assert subcommittee.comm_name == "테스트위원회 법안심사소위원회"

    budget = by_id[401]
    assert budget.meeting_type == "특별위"
    assert budget.comm_name == "예산결산특별위원회"

    audit = by_id[502]
    assert audit.meeting_type == "국정감사"
    assert audit.is_appendix is True
    assert audit.title.endswith("(부록)")
    assert [item.mnts_id for item in result.html_unavailable] == [699]

    assert all("type=summary" not in meeting.detail_url for meeting in meetings)
    assert all("download/pdf" not in meeting.detail_url for meeting in meetings)


def test_web_meeting_to_row_matches_meetings_schema() -> None:
    meeting = crawl_minutes_web_list(session=_FakeSession())[0]

    row = web_meeting_to_row(meeting)

    assert set(row) == {
        "mnts_id",
        "title",
        "meeting_type",
        "session_no",
        "degree",
        "conf_date",
        "comm_name",
        "is_temporary",
        "is_appendix",
    }
    assert row["mnts_id"] == meeting.mnts_id


def _entry_with_session(class_id: int) -> str:
    return f"""
    <ul class="tree_list">
      <li>
        <a class="tit sess" data-id="" data-sess="435" data-th="22" data-class="{class_id}"
           data-chk1="all" data-chk2="" data-chk3="" data-chk4="" data-year="">
          <strong>제435회</strong>
        </a>
      </li>
    </ul>
    """


def _entry_with_committee(class_id: int, name: str) -> str:
    return f"""
    <ul class="tree_list">
      <li>
        <a class="tit cmit" data-sess="" data-th="22" data-class="{class_id}"
           data-cmit="AA" data-chk1="all" data-chk2="" data-chk3="" data-chk4=""
           data-str="min" data-year="">
          <strong>{name}</strong>
        </a>
      </li>
    </ul>
    """


def _session_child(class_id: int) -> str:
    return f"""
    <li>
      <a class="tit sub" data-cmit="" data-th="22" data-sess="432" data-class="{class_id}"
         data-cmitCd="AA" data-chk1="all" data-chk2="" data-chk3="" data-chk4="">
        <strong>제432회</strong>
      </a>
    </li>
    """


def _year_child(class_id: int) -> str:
    return f"""
    <li>
      <a class="tit sub" data-cmit="" data-th="22" data-sess="" data-class="{class_id}"
         data-cmitCd="AA" data-dt="2025" data-chk1="all" data-chk2="" data-chk3=""
         data-chk4="">
        <strong>2025</strong>
      </a>
    </li>
    """


def _final_row(class_id: int, mnts_id: int) -> str:
    title = _title(class_id)
    title_attr = title if class_id != 1 else ""
    appendix = '<a class="btn_appendix">(부록)</a>' if class_id == 5 else ""
    temp = '<span class="temp">[임시]</span>' if class_id == 1 else ""
    missing_view = _missing_view_row(699) if class_id == 6 else ""
    return f"""
    <li>
      <div class="tit_wrap">
        <div class="txt">
          <a class="tit" data-id="{mnts_id}" data-sess="435" title="{title_attr}">
            <strong>{temp}{title}{appendix}</strong>
          </a>
        </div>
        <div class="btn_list">
          <a href="/assembly/viewer/minutes/download/pdf.do?id={mnts_id}">PDF</a>
          <a href="/assembly/viewer/minutes/xml.do?id={mnts_id}&type=view">회의록뷰어</a>
          <a href="/assembly/viewer/minutes/xml.do?id={mnts_id}&type=summary">회의정보</a>
        </div>
      </div>
    </li>
    {missing_view}
    """


def _missing_view_row(mnts_id: int) -> str:
    return f"""
    <li>
      <div class="tit_wrap">
        <div class="txt">
          <a class="tit" data-id="{mnts_id}" data-sess="435"
             title="HTML없는회의 제1차 (2026. 01. 31.)">
            <strong>HTML없는회의 제1차 (2026. 01. 31.)</strong>
          </a>
        </div>
        <div class="btn_list">
          <a href="/assembly/viewer/minutes/xml.do?id={mnts_id}&type=summary">회의정보</a>
        </div>
      </div>
    </li>
    """


def _committee_name(class_id: int) -> str:
    return {
        2: "테스트위원회 법안심사소위원회",
        3: "테스트특별위원회",
        5: "테스트위원회",
        6: "테스트국정조사특별위원회",
    }[class_id]


def _title(class_id: int) -> str:
    return {
        1: "제2차 (2026. 05. 08.)",
        2: "테스트위원회 법안심사소위원회 제1차 (2026. 02. 23.)",
        3: "테스트특별위원회 제8차 (2025. 12. 30.)",
        4: "예산결산특별위원회 제3차 (2026. 04. 10.)",
        5: "감사대상기관 (2025. 11. 06.)",
        6: "테스트국정조사특별위원회 제6차 (2026. 01. 30.)",
    }[class_id]
