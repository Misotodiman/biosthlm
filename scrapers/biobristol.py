# scrapers/biobristol.py
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.biobristol.se"
# URL-mönster: /program/today/popularity/all  eller  /program/YYYY-MM-DD/popularity/all
PROGRAM_URL = f"{BASE_URL}/program/{{date_part}}/popularity/all"


def _fetch_html(url: str, timeout: int) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; bio-schema-stockholm/1.0; +https://example.invalid)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text


def _parse_showings(html: str, wanted: date) -> list[dict[str, Any]]:
    """
    Parsar visningar från Bio Bristols server-renderade HTML.

    Strukturen per film:
      - <a> med filmtitel (länk till /f/slug/id)
      - Metadata-text med ålder, längd, genre
      - <a> med visning: "Bristol HH:MM format-info" (länk till /showtime/id)
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []

    # Hitta alla showtime-länkar (de pekar på /showtime/...)
    showtime_links = soup.find_all("a", href=re.compile(r"/showtime/"))

    for st_link in showtime_links:
        st_text = " ".join(st_link.get_text(" ", strip=True).split())
        booking_url = st_link.get("href", "")
        if booking_url.startswith("/"):
            booking_url = BASE_URL + booking_url

        # Extrahera tid: "Bristol 16:30 svensk text" → tid = "16:30"
        time_match = re.search(r"(\d{1,2}:\d{2})", st_text)
        if not time_match:
            continue
        start_time = time_match.group(1)

        # Venue (allt före tiden)
        venue_part = st_text[: time_match.start()].strip()
        venue = venue_part if venue_part else "Bristol"

        # Format-info (allt efter tiden)
        format_part = st_text[time_match.end():].strip()
        format_info = format_part if format_part else None

        # Hitta filmtitel: gå bakåt och leta efter närmaste <a> med /f/ länk
        title = None
        film_url = None
        # Sök i föregående element
        for prev in st_link.find_all_previous("a", href=re.compile(r"/f/")):
            title_text = " ".join(prev.get_text(" ", strip=True).split())
            if title_text and not title_text.startswith("http"):
                title = title_text
                film_url = prev.get("href", "")
                if film_url.startswith("/"):
                    film_url = BASE_URL + film_url
                break

        if not title:
            continue

        # Hämta metadata (ålder, längd, genre) — text mellan filmtiteln och showtimen
        meta_info = None
        parent = st_link.parent
        if parent:
            parent_text = " ".join(parent.get_text(" ", strip=True).split())
            # Leta efter mönster som "Från 7 år | 1t 54m | Drama"
            meta_match = re.search(
                r"((?:Från\s+)?\d+\s*år.*?)(?:Bristol|Sal\s)", parent_text
            )
            if meta_match:
                meta_info = meta_match.group(1).strip().rstrip("|").strip()

        rows.append(
            {
                "title": title,
                "cinema": "Bio Bristol",
                "start_time": start_time,
                "date": wanted.isoformat(),
                "booking_url": booking_url,
                "format_info": format_info,
                "venue": venue or "Bristol",
                "district": None,
                "source": "biobristol.se",
                "category": "film",
            }
        )

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


def fetch_biobristol(target_date: str, timeout: int = 20) -> list[dict[str, Any]]:
    """
    Hämtar visningar för ett specifikt datum från Bio Bristol.

    Sajten (Filmgrail-plattform) server-renderar HTML, så vi
    hämtar /program/{datum}/popularity/all och parsar.
    """
    wanted = date.fromisoformat(target_date)
    today = datetime.now().date()

    if wanted == today:
        date_part = "today"
    else:
        date_part = wanted.isoformat()

    url = PROGRAM_URL.format(date_part=date_part)
    html = _fetch_html(url, timeout=timeout)
    return _parse_showings(html, wanted)
