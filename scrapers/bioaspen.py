# scrapers/bioaspen.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag


STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")

BASE_URL = "https://www.bioaspen.se/visningar/filmer/"
BASE_HOST = "https://www.bioaspen.se"
USER_AGENT = "bioschema/1.0 (+https://example.com) python-requests"

# Svenska månader som Aspen typiskt använder i rubriker.
_MONTHS = {
    "januari": 1,
    "februari": 2,
    "mars": 3,
    "april": 4,
    "maj": 5,
    "juni": 6,
    "juli": 7,
    "augusti": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}

# Ex: "onsdag, 25 februari"
_DATE_HEADING_RE = re.compile(
    r"^\s*(måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag)\s*,\s*(\d{1,2})\s+([a-zåäö]+)\s*$",
    re.IGNORECASE,
)

# Ex: "13:45 Space Cadet 1 tim 26 min Barntillåten ..."
_ITEM_RE = re.compile(r"^\s*(?P<hh>\d{1,2}):(?P<mm>\d{2})\s+(?P<rest>.+?)\s*$")

# För att klippa bort metadata efter titel.
_TITLE_CUTOFF_RE = re.compile(r"\s+\d+\s+tim\b|\s+\d+\s+min\b", re.IGNORECASE)


@dataclass(frozen=True)
class AspenShow:
    title: str
    start_time: str
    date: str
    booking_url: Optional[str]


def _http_get(url: str, timeout: int) -> str:
    r = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.7",
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.text


def _coerce_target_date(target_date: str | date | None) -> date:
    if target_date is None:
        return datetime.now(STOCKHOLM_TZ).date()
    if isinstance(target_date, date):
        return target_date
    # main.py skickar ISO-sträng "YYYY-MM-DD"
    return date.fromisoformat(target_date)


def _parse_heading_to_date(heading_text: str, anchor: date) -> Optional[date]:
    """
    Aspen visar inte år. Vi gissar år relativt ankaret (target_date).
    """
    m = _DATE_HEADING_RE.match((heading_text or "").strip())
    if not m:
        return None

    day = int(m.group(2))
    month_name = m.group(3).lower()
    month = _MONTHS.get(month_name)
    if not month:
        return None

    y = anchor.year
    d = date(y, month, day)

    # Heuristik runt årsskifte relativt ankaret.
    if anchor.month == 12 and month == 1 and d < anchor:
        d = date(y + 1, month, day)
    if anchor.month == 1 and month == 12 and d > anchor:
        d = date(y - 1, month, day)

    return d


def _extract_title(rest: str) -> str:
    rest = (rest or "").strip()
    m = _TITLE_CUTOFF_RE.search(rest)
    if not m:
        return rest
    return rest[: m.start()].strip()


def _iter_relevant_tags_in_order(soup: BeautifulSoup) -> Iterable[Tag]:
    """
    Iterera DOM i ordning och yielda rubriker + länkar.
    Mer tolerant än hårda CSS-selektorer.
    """
    root = soup.body or soup
    for el in root.descendants:
        if not isinstance(el, Tag):
            continue
        if el.name in ("h2", "h3"):
            yield el
        elif el.name == "a" and el.get("href"):
            yield el


def _abs_url(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return BASE_HOST + href
    return BASE_HOST + "/" + href.lstrip("/")


def fetch_bioaspen(
    *,
    target_date: str | date | None = None,
    timeout: int = 20,
    max_pages: int = 6,
    **_kwargs,
) -> list[dict]:
    """
    Kompatibel med main.py:
      - tar emot target_date som ISO-sträng eller date
      - tar emot timeout
      - returnerar dictar som matchar Show i main.py
    """
    td = _coerce_target_date(target_date)
    td_iso = td.isoformat()

    results: list[dict] = []
    seen = set()

    for page in range(1, max_pages + 1):
        url = BASE_URL if page == 1 else f"{BASE_URL}page/{page}/"
        html = _http_get(url, timeout=timeout)
        soup = BeautifulSoup(html, "html.parser")

        current_date: Optional[date] = None
        saw_any_heading = False
        saw_any_items_for_target = False

        for tag in _iter_relevant_tags_in_order(soup):
            if tag.name in ("h2", "h3"):
                d = _parse_heading_to_date(tag.get_text(" ", strip=True), anchor=td)
                if d:
                    current_date = d
                    saw_any_heading = True
                continue

            if tag.name == "a" and current_date is not None:
                # Vi bryr oss bara om target_date
                if current_date != td:
                    continue

                text = tag.get_text(" ", strip=True)
                m = _ITEM_RE.match(text)
                if not m:
                    continue

                hh = int(m.group("hh"))
                mm = int(m.group("mm"))
                start_time = f"{hh:02d}:{mm:02d}"

                rest = m.group("rest").strip()
                title = _extract_title(rest)
                booking_url = _abs_url(tag.get("href", "")) or None

                # Dedup
                key = (td_iso, start_time, title, booking_url or "")
                if key in seen:
                    continue
                seen.add(key)

                results.append(
                    {
                        "title": title,
                        "cinema": "Bio Aspen",
                        "start_time": start_time,
                        "date": td_iso,
                        "booking_url": booking_url,
                        "format_info": None,
                        "district": "Aspudden",
                        "venue": None,
                        "source": "bioaspen.se",
                        "category": "film",
                    }
                )
                saw_any_items_for_target = True

        # Om markup/paginering tog slut
        if not saw_any_heading:
            break

        # Om vi hittade visningar för target_date på den här sidan så kan det ändå finnas fler på nästa,
        # så vi fortsätter. Men om vi inte hittade några alls för target_date och vi är förbi första sidan,
        # kan vi bryta tidigare för att spara tid.
        if page > 1 and not saw_any_items_for_target:
            break

    return results
