# scrapers/capitol.py
from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .common import get_html

BASE_URL = "https://www.capitolbio.se"
FILMER_URL = f"{BASE_URL}/filmer"


def _extract_title_and_time(a_tag: Tag) -> tuple[str, str] | None:
    """Plocka ut ren titel och starttid från en Capitol-titellänk.

    Strukturen ser ut så här:
      <a href="/boka/50268">
        Josef Mengeles försvinnande
        <span class="sr-only">(17:20)</span>
        <span>...badges (salong + koncept)...</span>
      </a>

    Vi vill ha titeln UTAN tid och UTAN badges.
    """
    # sr-only-spannet innehåller "(HH:MM)" — pålitlig tidskälla
    sr_only = a_tag.find("span", class_=lambda c: c and "sr-only" in c)
    time_match = None
    if sr_only:
        sr_text = sr_only.get_text(" ", strip=True)
        time_match = re.search(r"\(\s*(\d{1,2}:\d{2})\s*\)", sr_text)

    if not time_match:
        # Fallback: sök tid i hela länktexten
        full_text = a_tag.get_text(" ", strip=True)
        time_match = re.search(r"\(\s*(\d{1,2}:\d{2})\s*\)", full_text)
        if not time_match:
            return None

    start_time = time_match.group(1)

    # För ren titel: iterera direkt-children och ta bara textnoder
    # utanför span-element (span innehåller tid, salong, badges).
    title_parts: list[str] = []
    for child in a_tag.children:
        if isinstance(child, Tag):
            if child.name == "span":
                continue
            t = child.get_text(" ", strip=True)
            if t:
                title_parts.append(t)
        else:
            t = str(child).strip()
            if t:
                title_parts.append(t)

    title = " ".join(title_parts).strip()
    title = re.sub(r"\s+", " ", title)

    if not title:
        return None

    return title, start_time


def _extract_venue(a_tag: Tag) -> str | None:
    """Hitta salong från badges inuti titel-länken.

    Badge-struktur:
      <span class="sr-only">Salong </span><span>4</span>
    """
    for sr in a_tag.find_all("span", class_=lambda c: c and "sr-only" in c):
        if "salong" in sr.get_text(" ", strip=True).lower():
            sibling = sr.find_next_sibling("span")
            if sibling:
                num = re.search(r"\d+", sibling.get_text(" ", strip=True))
                if num:
                    return f"Salong {num.group(0)}"
    return None


def _extract_format_from_row(a_tag: Tag) -> str | None:
    """Plocka ut koncept och språk från raden direkt efter titeln.

    Raden ligger som ett <div>-syskon direkt efter titel-länken och innehåller
    strukturen: '17:20 · Dine-in · DE tal | SV text'.
    """
    row_div = a_tag.find_next_sibling("div")
    if row_div is None:
        return None

    text = row_div.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    # Ta bort tid i början
    text = re.sub(r"^\s*\d{1,2}:\d{2}\s*[·\-]?\s*", "", text)

    if not text:
        return None
    return text


def _parse_showings(html: str, wanted: date) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []

    # Alla titel-länkar går till /boka/{id}
    for a in soup.find_all("a", href=re.compile(r"^/boka/\d+")):
        parsed = _extract_title_and_time(a)
        if not parsed:
            continue
        title, start_time = parsed

        venue = _extract_venue(a)
        format_info = _extract_format_from_row(a)
        booking_url = urljoin(BASE_URL, a["href"])

        rows.append({
            "title": title,
            "cinema": "Capitol",
            "start_time": start_time,
            "date": wanted.isoformat(),
            "booking_url": booking_url,
            "format_info": format_info,
            "venue": venue,
            "district": None,
            "source": "capitolbio.se",
            "category": "film",
        })

    # Dedup
    seen = set()
    uniq: list[dict[str, Any]] = []
    for r in rows:
        k = (r["date"], r["start_time"], r["title"].lower(), r.get("venue"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


def fetch_capitol(target_date: str, timeout: int = 20):
    wanted = date.fromisoformat(target_date)
    url = f"{FILMER_URL}?datum={wanted.isoformat()}"
    html = get_html(url, timeout=timeout)
    return _parse_showings(html, wanted)
