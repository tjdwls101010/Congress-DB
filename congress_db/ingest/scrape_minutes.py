"""회의록 HTML fetch/parse."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import hanja
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://record.assembly.go.kr/assembly/viewer/minutes/xml.do"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


@dataclass(frozen=True)
class MinutesInfo:
    """회의록 HTML에서 읽은 회의 메타."""

    mnts_id: int
    title: str
    date: str
    url: str | None


@dataclass(frozen=True)
class UtteranceDraft:
    """DB 적재 전 발언."""

    meeting_id: int
    sequence: int
    speaker_name: str
    speaker_title: str
    content: str


@dataclass(frozen=True)
class MinutesDomProfile:
    """회의록 DOM 구조 검증 결과."""

    mnts_id: int
    title: str
    has_minutes_body: bool
    speaker_count: int
    data_name_count: int
    data_pos_count: int
    talk_txt_count: int
    spk_sub_speaker_count: int
    utterance_count: int
    first_speaker_class: str | None


def fetch_minutes(mnts_id: int, *, timeout: int = 30) -> tuple[str, str]:
    """회의록 HTML을 가져온다."""
    response = requests.get(
        BASE_URL,
        params={"id": str(mnts_id), "type": "view"},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    url = f"{BASE_URL}?id={mnts_id}&type=view"
    return response.text, url


def inspect_minutes_dom(html: str, mnts_id: int) -> MinutesDomProfile:
    """회의록 DOM이 파서가 기대하는 구조인지 계수로 확인한다."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".minutes_body")
    speakers = list(body.find_all("div", class_="speaker")) if body else []
    _, utterances = parse_minutes(html, mnts_id)
    return MinutesDomProfile(
        mnts_id=mnts_id,
        title=_parse_title(soup, mnts_id),
        has_minutes_body=body is not None,
        speaker_count=len(speakers),
        data_name_count=sum(1 for speaker in speakers if speaker.get("data-name")),
        data_pos_count=sum(1 for speaker in speakers if speaker.get("data-pos")),
        talk_txt_count=sum(1 for speaker in speakers if speaker.select_one(".talk .txt")),
        spk_sub_speaker_count=sum(
            1
            for speaker in speakers
            if speaker.select_one(".talk .txt span.spk_sub")
        ),
        utterance_count=len(utterances),
        first_speaker_class=" ".join(speakers[0].get("class", [])) if speakers else None,
    )


def parse_minutes(
    html: str,
    mnts_id: int,
    url: str | None = None,
) -> tuple[MinutesInfo, list[UtteranceDraft]]:
    """회의록 HTML을 발언 단위로 파싱한다."""
    soup = BeautifulSoup(html, "html.parser")
    title = _parse_title(soup, mnts_id)
    meeting_info = MinutesInfo(
        mnts_id=mnts_id,
        title=title,
        date=_parse_meeting_date(soup, title),
        url=url,
    )

    body = soup.select_one(".minutes_body")
    if not body:
        return meeting_info, []

    utterances: list[UtteranceDraft] = []
    seen_sequences: set[int] = set()
    for div in body.find_all("div", class_="speaker"):
        sequence = _speaker_sequence(div.get("id"))
        if sequence is None or sequence in seen_sequences:
            continue
        seen_sequences.add(sequence)

        speaker_name = normalize_speaker_name(div.get("data-name"))
        speaker_title = str(div.get("data-pos") or "").strip()
        if not speaker_name:
            continue

        content = _speaker_content(div)
        if not content:
            continue

        utterances.append(
            UtteranceDraft(
                meeting_id=mnts_id,
                sequence=sequence,
                speaker_name=speaker_name,
                speaker_title=speaker_title,
                content=content,
            )
        )

    return meeting_info, utterances


def match_member(name: str, all_members_dict: dict[str, str]) -> str | None:
    """정규화된 이름이 유일한 의원명과 일치하면 `mona_cd`를 반환한다."""
    return all_members_dict.get(normalize_speaker_name(name))


def normalize_speaker_name(value: Any) -> str:
    """한자 이름을 한글로 바꾸고 Unicode 폭 차이를 정규화한다."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return hanja.translate(text, "substitution").strip()


def _parse_title(soup: BeautifulSoup, mnts_id: int) -> str:
    h2 = soup.find("h2")
    title = h2.get_text(strip=True) if h2 else ""
    return title or f"회의록 {mnts_id}"


def _parse_meeting_date(soup: BeautifulSoup, title: str) -> str:
    place = soup.select_one(".minutes_header .place")
    if place:
        for item in place.find_all("li"):
            label = item.select_one(".sbj")
            value = item.select_one(".con")
            if label and value and "일시" in label.get_text():
                parsed = _parse_korean_date(value.get_text())
                if parsed:
                    return parsed

    title_match = re.search(r"\((\d{4})[.-](\d{2})[.-](\d{2})\.?\)", title)
    if title_match:
        return "-".join(title_match.groups())
    return "unknown"


def _parse_korean_date(value: str) -> str | None:
    match = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", value)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def _speaker_sequence(value: Any) -> int | None:
    match = re.match(r"spk_(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def _speaker_content(div: Any) -> str:
    talk = div.select_one(".talk .txt")
    if not talk:
        return ""
    spans = talk.find_all("span", class_="spk_sub")
    if spans:
        return "\n".join(span.get_text(strip=True) for span in spans if span.get_text(strip=True))
    return talk.get_text(" ", strip=True)
