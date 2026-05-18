# scrapers/biobristol.py
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup

from .common import get_html

BASE_URL = "https://www.biobristol.se"
# Filmgrail-plattformen. URL-mönster (OBS: TVÅ /all — screen + ageRating):
#   /program/{datum}/popularity/all/all?noMaster=true
# {datum} är ett ISO-datum (YYYY-MM-DD).
#
# VIKTIGT: med noMaster=true returnerar servern JSON, inte rå HTML:
#   {"master": "...", "pageTitle": "...", "html": "<faktiska HTML-fragmentet>"}
# Vi måste packa upp "html"-fältet innan vi tolkar det med BeautifulSoup.
PROGRAM_URL = BASE_URL + "/program/{date_part}/popularity/all/all?noMaster=true"

# Ljudformat och tekniska taggar vi INTE vill ha med i format_info.
_SKIP_NOTES = re.compile(
    r"^(picture format|5\.1|7\.1|2\.0|dolby|atmos|vf|of)\b",
    flags=re.I,
)


def _extract_html(raw: str) -> str:
    """
    Bristol/Filmgrail svarar med JSON där HTML-fragmentet ligger i "html".
    Packar upp det. Om svaret redan är rå HTML returneras det oförändrat.
    """
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("html"), str):
            return data["html"]
    except (json.JSONDecodeError, ValueError):
        pass
    return raw


def _selected_date(soup: BeautifulSoup) -> str | None:
    """
    Läser vilket datum programmet faktiskt gäller, från datumväljaren:
      <select id="ProgramFilters_dates">
        <option value="2026-05-20" selected="selected">ons 20 maj</option>
    Om vi ber om ett datum Bristol inte har program för, returnerar servern
    närmaste tillgängliga datum istället — då vill vi INTE stämpla fel datum.
    """
    sel = soup.select_one("#ProgramFilters_dates option[selected]")
    if sel and sel.get("value"):
        return sel.get("value").strip()
    return None


def _parse_showtime(st_link, title: str, target_date: str) -> dict[str, Any] | None:
    """Parsar en enskild <a class="showtime-wrap"> till en visningsrad."""
    href = st_link.get("href", "")
    booking_url = BASE_URL + href if href.startswith("/") else href

    time_el = st_link.select_one(".program__showtimeTime")
    if not time_el:
        return None
    tm = re.search(r"(\d{1,2}:\d{2})", time_el.get_text(" ", strip=True))
    if not tm:
        return None
    start_time = tm.group(1)

    venue = None
    prov_el = st_link.select_one(".program__showtimeProvider")
    if prov_el:
        v = prov_el.get_text(" ", strip=True)
        if v:
            venue = v

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

    # Verifiera att svaret gäller datumet vi bad om. Om Bristol saknar
    # program för target_date returnerar servern närmaste datum istället —
    # då returnerar vi tomt hellre än att stämpla fel datum på visningarna.
    sel = _selected_date(soup)
    if sel is not None and sel != target_date:
        return []

    rows: list[dict[str, Any]] = []
    for card in soup.select("div.movie-card"):
        title_el = card.select_one("a.movie-title")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title:
            continue
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

    Bio Bristol kör Filmgrail-plattformen. Programmet hämtas via
    /program/{datum}/popularity/all/all?noMaster=true, som returnerar JSON
    med HTML-fragmentet i "html"-nyckeln.

    OBS: Bristol publicerar tider för kommande helg t.o.m. torsdag
    vanligtvis först onsdag morgon — så framtida datum kan ge 0 träffar
    helt korrekt (inte ett scraper-fel).
    """
    # Validera datumformatet (kastar ValueError om ogiltigt)
    date.fromisoformat(target_date)

    url = PROGRAM_URL.format(date_part=target_date)
    raw = get_html(url, timeout=timeout)
    html = _extract_html(raw)
    return _parse_program(html, target_date)
