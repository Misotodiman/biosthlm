from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common import get_html, clean_spaces


BASE_URL = "https://tellusbio.nu"
DAY_URL_TMPL = f"{BASE_URL}/programmet/kategori/film/{{date}}/"

_TIME_RE = re.compile(r"^\s*\d{1,2}:\d{2}\s*$")


def _extract_booking_url(event_url: str, timeout: int) -> Optional[str]:
    """På event-sidorna finns en "Köp biljett"-länk till nortic.se."""
    try:
        html = get_html(event_url, timeout=timeout)
    except Exception:
        return None

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True).lower()
        if "köp biljett" in t or "köp biljetter" in t:
            return a["href"]
    return None


def fetch_tellus(target_date: str, timeout: int = 20):
    """Hämtar visningar från Tellus dag-vy.

    Strukturen i HTML:en är (förenklat):
      <h2>19:30</h2>           ← starttid
      [eventuell pris-text]
      <h2><a>Filmtitel</a></h2> ← titel + länk till event-sidan
    """
    url = DAY_URL_TMPL.format(date=target_date)
    html = get_html(url, timeout=timeout)
    soup = BeautifulSoup(html, "html.parser")

    h2s = soup.find_all("h2")

    rows: list[dict[str, Any]] = []
    seen = set()

    i = 0
    while i < len(h2s):
        h2 = h2s[i]
        h2_text = clean_spaces(h2.get_text(" ", strip=True))
        if not h2_text or not _TIME_RE.match(h2_text):
            i += 1
            continue

        start_time = h2_text

        # Leta efter nästa h2 som innehåller en länk (titel)
        j = i + 1
        title = None
        event_url = None
        while j < len(h2s):
            h2b = h2s[j]
            t = clean_spaces(h2b.get_text(" ", strip=True))
            # Ny tid-h2 innan vi hittat titeln → ge upp
            if t and _TIME_RE.match(t):
                break

            a = h2b.find("a", href=True)
            if a:
                title = clean_spaces(a.get_text(" ", strip=True))
                event_url = urljoin(BASE_URL, a["href"])
                break
            j += 1

        if title and event_url:
            booking_url = _extract_booking_url(event_url, timeout=timeout)

            key = (target_date, start_time, title.lower())
            if key not in seen:
                seen.add(key)
                rows.append({
                    "title": title,
                    "cinema": "Tellus",
                    "start_time": start_time,
                    "date": target_date,
                    "booking_url": booking_url,
                    "format_info": None,  # ingen pris/skräp längre
                    "district": "Midsommarkransen",
                    "venue": None,
                    "source": "tellusbio.nu/programmet",
                    "category": "film",
                })

        i = j + 1 if j > i else i + 1

    return rows
