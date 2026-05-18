# scrapers/biobristol.py
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup

from .common import get_html

BASE_URL = "https://www.biobristol.se"
# Filmgrail-plattformen. URL-mönster (OBS: TVÅ /all — screen + ageRating):
#   /program/{datum}/popularity/all/all?noMaster=true
# noMaster=true ger en ren HTML-fragment utan sidhuvud/sidfot.
# {datum} är "today" eller "YYYY-MM-DD".
PROGRAM_URL = BASE_URL + "/program/{date_part}/popularity/all/all?noMaster=true"

# Ljudformat och tekniska taggar vi INTE vill ha med i format_info.
# clean_format_info i main.py rensar mycket av detta ändå, men vi filtrerar
# bort det uppenbara redan här så datan blir renare.
_SKIP_NOTES = re.compile(
    r"^(picture format|5\.1|7\.1|2\.0|dolby|atmos|vf|of)\b",
    flags=re.I,
)


def _parse_showtime(st_link, title: str, target_date: str) -> dict[str, Any] | None:
    """Parsar en enskild <a class="showtime-wrap"> till en visningsrad."""
    # Bokningslänk: href är /showtime/{id}
    href = st_link.get("href", "")
    booking_url = BASE_URL + href if href.startswith("/") else href

    # Klockslag
    time_el = st_link.select_one(".program__showtimeTime")
    if not time_el:
        return None
    tm = re.search(r"(\d{1,2}:\d{2})", time_el.get_text(" ", strip=True))
    if not tm:
        return None
    start_time = tm.group(1)

    # Salong: "Bristol" eller "Sal 1" — ligger i showtimeProvider
    venue = None
    prov_el = st_link.select_one(".program__showtimeProvider")
    if prov_el:
        v = prov_el.get_text(" ", strip=True)
        if v:
            venue = v

    # Taggar: "svensk text", "5.1", "picture format: vf" osv.
    # Vi behåller språk-/textinfo men hoppar över rena ljud-/teknik-taggar.
    notes = []
    for note_el in st_link.select(".program__showtimeNotes"):
        note = note_el.get_text(" ", strip=True)
        if note and not _SKIP_NOTES.match(note):
            notes.append(note)
    format_info = " · ".join(notes) if notes else None

    return {
        "title": title,
        "cinema": "Bio Bristol",
        "start_time": start_time,
        "date": target_date,
        "booking_url": booking_url,
        "format_info": format_info,
        "venue": venue,
        "district": None,
        "source": "biobristol.se",
        "category": "film",
    }


def _parse_program(html: str, target_date: str) -> list[dict[str, Any]]:
    """Parsar alla visningar ur Bio Bristols program-fragment."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []

    # Varje film är en .movie-card med titel + visningar
    for card in soup.select("div.movie-card"):
        title_el = card.select_one("a.movie-title")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title:
            continue

        # Alla visningar inom detta filmkort
        for st_link in card.select("a.showtime-wrap"):
            row = _parse_showtime(st_link, title, target_date)
            if row:
                rows.append(row)

    # Dedup på (datum, tid, titel, salong)
    seen = set()
    uniq: list[dict[str, Any]] = []
    for r in rows:
        k = (r["date"], r["start_time"], r["title"].lower(), r.get("venue"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    return sorted(uniq, key=lambda x: (x["start_time"], x["title"].lower()))


def fetch_biobristol(target_date: str, timeout: int = 20) -> list[dict[str, Any]]:
    """
    Hämtar visningar för ett specifikt datum från Bio Bristol.

    Bio Bristol kör Filmgrail-plattformen. Programmet hämtas som ett
    HTML-fragment via /program/{datum}/popularity/all/all?noMaster=true.

    OBS: Bristol publicerar tider för kommande helg t.o.m. torsdag
    vanligtvis först onsdag morgon — så framtida datum kan ge 0 träffar
    helt korrekt (inte ett scraper-fel).
    """
    wanted = date.fromisoformat(target_date)
    today = datetime.now().date()
    date_part = "today" if wanted == today else wanted.isoformat()

    url = PROGRAM_URL.format(date_part=date_part)
    html = get_html(url, timeout=timeout)
    return _parse_program(html, target_date)
