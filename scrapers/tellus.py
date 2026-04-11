from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://tellusbio.nu"
DAY_URL_TMPL = f"{BASE_URL}/programmet/kategori/film/{{date}}/"


_TIME_RE = re.compile(r"^\s*\d{1,2}:\d{2}\s*$", re.IGNORECASE)
_KL_TIME_RE = re.compile(r"\bkl\.?\s*(\d{1,2}:\d{2})\b", re.IGNORECASE)


def _get_html(url: str, timeout: int) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; bio-schema-stockholm/1.0; +https://example.invalid)",
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text


def _clean(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s2 = " ".join(s.strip().split())
    return s2 or None


def _extract_booking_url(event_url: str, timeout: int) -> Optional[str]:
    """
    På event-sidorna finns ofta en länk med text "Köp biljett" (ibland "Köp biljetter").
    Den länkar vanligtvis till nortic.se.
    """
    try:
        html = _get_html(event_url, timeout=timeout)
    except Exception:
        return None

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        t = a.get_text(" ", strip=True).lower()
        if "köp biljett" in t or "köp biljetter" in t:
            return a["href"]
    return None


def _extract_price_near(h2_time_tag) -> Optional[str]:
    """
    I dag-vyn ligger pris ofta mellan tid-h2 och titel-h2 (t.ex. "80 kr").
    Vi tar första rimliga textnoden efter tid-h2 innan nästa h2.
    """
    cur = h2_time_tag
    while True:
        cur = cur.find_next_sibling()
        if cur is None:
            return None
        if getattr(cur, "name", None) == "h2":
            return None
        txt = _clean(cur.get_text(" ", strip=True) if hasattr(cur, "get_text") else None)
        if not txt:
            continue
        # Ex: "80 kr" eller "90 kr – 165 kr"
        if "kr" in txt.lower():
            # korta ner lite om det är väldigt mycket text
            return txt[:80]
    # unreachable


def fetch_tellus(target_date: str, timeout: int = 20):
    """
    Returnerar list[dict] med keys som matchar Show i main.py:
    title, cinema, start_time, date, booking_url, format_info, district, venue, source, category
    """
    url = DAY_URL_TMPL.format(date=target_date)
    html = _get_html(url, timeout=timeout)
    soup = BeautifulSoup(html, "html.parser")

    h2s = soup.find_all("h2")

    rows: list[dict[str, Any]] = []
    seen = set()

    i = 0
    while i < len(h2s):
        h2 = h2s[i]
        h2_text = _clean(h2.get_text(" ", strip=True))
        if not h2_text or not _TIME_RE.match(h2_text):
            i += 1
            continue

        start_time = h2_text
        price = _extract_price_near(h2)

        # Leta efter nästa h2 som innehåller en länk (titel)
        j = i + 1
        title = None
        event_url = None
        while j < len(h2s):
            h2b = h2s[j]
            # Om vi stöter på en ny tid-h2 innan titel-h2, ge upp (ovanligt men robust)
            t = _clean(h2b.get_text(" ", strip=True))
            if t and _TIME_RE.match(t):
                break

            a = h2b.find("a", href=True)
            if a:
                title = _clean(a.get_text(" ", strip=True))
                event_url = urljoin(BASE_URL, a["href"])
                break
            j += 1

        if title and event_url:
            # booking_url från detaljsidan om möjligt
            booking_url = _extract_booking_url(event_url, timeout=timeout)

            # format_info: pris + ev. något mer (om du vill hålla det superrent kan du sätta None här)
            format_info = price

            k = (target_date, start_time, title.lower())
            if k not in seen:
                seen.add(k)
                rows.append({
                    "title": title,
                    "cinema": "Tellus",
                    "start_time": start_time,
                    "date": target_date,
                    "booking_url": booking_url,
                    "format_info": format_info,
                    "district": "Midsommarkransen",
                    "venue": None,
                    "source": "tellusbio.nu/programmet",
                    "category": "film",
                })

        i = j + 1 if j > i else i + 1

    return rows
