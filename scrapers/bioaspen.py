# scrapers/bioaspen.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from .common import get_html


STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")

BASE_URL = "https://www.bioaspen.se/visningar/filmer/"
BASE_HOST = "https://www.bioaspen.se"

_MONTHS = {
    "januari": 1, "februari": 2, "mars": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "augusti": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}

# "onsdag, 25 februari"
_DATE_HEADING_RE = re.compile(
    r"^\s*(måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag)\s*,\s*(\d{1,2})\s+([a-zåäö]+)\s*$",
    re.IGNORECASE,
)

# "13:45 ..."
_TIME_PREFIX_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\b")

# Salong 1 / Lusoperan
_VENUE_RE = re.compile(r"\b(Salong\s*\d+|Lusoperan)\b", re.IGNORECASE)

# Klipp bort filmlängd och allt efter ("1 tim 26 min", "0 tim 42 min")
_LENGTH_RE = re.compile(r"\s*\d+\s+tim(?:\s+\d+\s+min)?", re.IGNORECASE)

# Specialvisningar som ofta står i titeln efter " - "
_SPECIAL_KEYWORDS = (
    "barnvagnsbio", "seniorbio", "frukostbio", "regibesök", "regissörsbesök",
    "specialvisning", "premiärvisning", "förhandsvisning", "tillgänglig bio",
    "med samtal", "och samtal", "skådespelarbesök", "engelsk undertext",
    "english subtitles", "svenskt tal", "engelskt tal", "klassiker",
    "aspen classics", "kulturnatten", "livepodd", "medverkandebesök",
    "tarantino", "äitienpäivä",
)


@dataclass(frozen=True)
class _Item:
    start_time: str
    title: str
    venue: Optional[str]
    format_info: Optional[str]
    booking_url: Optional[str]


def _coerce_date(target_date: str | date | None) -> date:
    if target_date is None:
        return datetime.now(STOCKHOLM_TZ).date()
    if isinstance(target_date, date):
        return target_date
    return date.fromisoformat(target_date)


def _heading_to_date(text: str, anchor: date) -> Optional[date]:
    m = _DATE_HEADING_RE.match((text or "").strip())
    if not m:
        return None
    day = int(m.group(2))
    month = _MONTHS.get(m.group(3).lower())
    if not month:
        return None
    y = anchor.year
    d = date(y, month, day)
    if anchor.month == 12 and month == 1 and d < anchor:
        d = date(y + 1, month, day)
    if anchor.month == 1 and month == 12 and d > anchor:
        d = date(y - 1, month, day)
    return d


def _abs_url(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return BASE_HOST + href
    return BASE_HOST + "/" + href.lstrip("/")


def _extract_specials(title: str) -> tuple[str, list[str]]:
    """Plocka ut specialvisningar ur titeln.

    'En Poet - specialvisning med poesi och livemusik!' → ('En Poet', ['specialvisning med poesi och livemusik'])
    'Father Mother Sister Brother - Barnvagnsbio' → ('Father Mother Sister Brother', ['Barnvagnsbio'])
    """
    extras: list[str] = []
    parts = title.split(" - ")
    if len(parts) < 2:
        return title.strip(), extras

    base = parts[0].strip()
    suffixes = [p.strip().rstrip("!").strip() for p in parts[1:]]

    # Behåll bara suffix som ser ut som specialvisningar
    for s in suffixes:
        s_low = s.lower()
        if any(kw in s_low for kw in _SPECIAL_KEYWORDS):
            extras.append(s)
        else:
            # Okänt suffix — behåll i titeln
            base = base + " - " + s
    return base.strip(), extras


def _parse_link(a_tag: Tag) -> Optional[_Item]:
    """Tolka en <a>-tagg som motsvarar en visning på Aspen-sidan."""
    text = a_tag.get_text("\n", strip=True)
    if not text:
        return None

    # Första raden ska vara tiden
    m = _TIME_PREFIX_RE.match(text)
    if not m:
        return None
    start_time = f"{int(m.group(1)):02d}:{m.group(2)}"

    # Plocka ut salong från hela texten
    venue_match = _VENUE_RE.search(text)
    venue: Optional[str] = None
    if venue_match:
        v = venue_match.group(1)
        # Normalisera "Salong 1" / "Lusoperan"
        if v.lower().startswith("salong"):
            venue = "Salong " + re.search(r"\d+", v).group(0)
        else:
            venue = "Lusoperan"

    # Titel: rad efter tiden, före "X tim Y min"
    # Splitta upp i rader, hoppa över första (tiden) och leta titeln
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    title = ""
    for line in lines[1:]:
        # Hoppa över "X tim Y min", åldersgränser, ljudformat, språk, salong
        if _LENGTH_RE.search(line):
            break
        if line.lower().startswith(("ljud", "tal ", "text ", "från ", "barntillåten", "salong", "lusoperan", "inga undertext")):
            continue
        if not title:
            title = line

    if not title:
        return None

    # Plocka ut specialvisningar ur titeln
    title, specials = _extract_specials(title)
    format_info = ", ".join(specials) if specials else None

    booking_url = _abs_url(a_tag.get("href", "")) or None

    return _Item(
        start_time=start_time,
        title=title,
        venue=venue,
        format_info=format_info,
        booking_url=booking_url,
    )


def _iter_relevant(soup: BeautifulSoup) -> Iterable[Tag]:
    root = soup.body or soup
    for el in root.descendants:
        if isinstance(el, Tag) and el.name in ("h2", "h3", "a"):
            if el.name == "a" and not el.get("href"):
                continue
            yield el


def fetch_bioaspen(
    *,
    target_date: str | date | None = None,
    timeout: int = 20,
    max_pages: int = 6,
    **_kwargs,
) -> list[dict]:
    td = _coerce_date(target_date)
    td_iso = td.isoformat()

    results: list[dict] = []
    seen = set()

    for page in range(1, max_pages + 1):
        url = BASE_URL if page == 1 else f"{BASE_URL}page/{page}/"
        try:
            html = get_html(url, timeout=timeout)
        except Exception:
            break
        soup = BeautifulSoup(html, "html.parser")

        current_date: Optional[date] = None
        saw_any_heading = False
        saw_any_for_target = False

        for tag in _iter_relevant(soup):
            if tag.name in ("h2", "h3"):
                d = _heading_to_date(tag.get_text(" ", strip=True), anchor=td)
                if d:
                    current_date = d
                    saw_any_heading = True
                continue

            if current_date != td:
                continue

            item = _parse_link(tag)
            if not item:
                continue

            key = (td_iso, item.start_time, item.title.lower())
            if key in seen:
                continue
            seen.add(key)

            results.append({
                "title": item.title,
                "cinema": "Bio Aspen",
                "start_time": item.start_time,
                "date": td_iso,
                "booking_url": item.booking_url,
                "format_info": item.format_info,
                "district": "Aspudden",
                "venue": item.venue,
                "source": "bioaspen.se",
                "category": "film",
            })
            saw_any_for_target = True

        if not saw_any_heading:
            break
        if page > 1 and not saw_any_for_target:
            break

    return results
