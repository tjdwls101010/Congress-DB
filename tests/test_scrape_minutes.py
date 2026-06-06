"""회의록 HTML 파싱 검증."""

from congress_db.ingest.scrape_minutes import inspect_minutes_dom, match_member, parse_minutes


def test_parse_minutes_extracts_utterances_and_translates_hanja() -> None:
    html = """
    <html>
      <body>
        <h2>제22대국회 제435회 제1차 테스트위원회(2026.05.20.)</h2>
        <div class="minutes_header">
          <ul class="place">
            <li><span class="sbj">일시</span><span class="con">2026년 5월 20일(수)</span></li>
          </ul>
        </div>
        <div class="minutes_body">
          <div id="spk_1" class="speaker" data-name="李憲昇" data-pos="위원">
            <div class="talk"><div class="txt">
              <span class="spk_sub">첫 번째 발언입니다.</span>
              <span class="spk_sub">두 번째 문단입니다.</span>
            </div></div>
          </div>
          <div id="spk_2" class="speaker" data-name="국무위원 홍길동" data-pos="장관">
            <div class="talk"><div class="txt">정부 답변입니다.</div></div>
          </div>
        </div>
      </body>
    </html>
    """

    meeting_info, utterances = parse_minutes(html, 920001, "https://example.com")

    assert meeting_info.mnts_id == 920001
    assert meeting_info.date == "2026-05-20"
    assert [utterance.sequence for utterance in utterances] == [1, 2]
    assert utterances[0].speaker_name == "이헌승"
    assert utterances[0].speaker_title == "위원"
    assert utterances[0].content == "첫 번째 발언입니다.\n두 번째 문단입니다."
    assert utterances[1].speaker_name == "국무위원 홍길동"


def test_match_member_uses_unique_normalized_name() -> None:
    members = {"이헌승": "TEST_MEMBER_1"}

    assert match_member("李憲昇", members) == "TEST_MEMBER_1"
    assert match_member("홍길동", members) is None


def test_inspect_minutes_dom_counts_parser_selectors() -> None:
    html = """
    <div class="minutes_body">
      <div id="spk_1" class="item0 speaker spk_mem" data-name="김테스트" data-pos="위원">
        <div class="talk"><div class="txt"><span class="spk_sub">발언</span></div></div>
      </div>
    </div>
    """

    profile = inspect_minutes_dom(html, 920001)

    assert profile.has_minutes_body is True
    assert profile.speaker_count == 1
    assert profile.data_name_count == 1
    assert profile.data_pos_count == 1
    assert profile.talk_txt_count == 1
    assert profile.spk_sub_speaker_count == 1
    assert profile.utterance_count == 1
    assert profile.first_speaker_class == "item0 speaker spk_mem"
