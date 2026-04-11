# scrapers/capitol.py
from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.capitolbio.se"
FILMER_URL = f"{BASE_URL}/filmer"


def _fetch_html(url: str, timeout: int) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; bio-schema-stockholm/1.0; +https://example.invalid)",
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text


def _parse_showings(html: str, wanted: date) -> list[dict[str, Any]]:
    """
    Parsar visningar från /filmer?datum=YYYY-MM-DD.

    Letar efter länkar med filmtitel + tid i formatet "Titel (HH:MM)"
    samt salong, format-info och bokningslänk i omgivande HTML.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []

    # Hitta alla a-taggar som innehåller "(HH:MM)" — dvs filmkort
    for a in soup.find_all("a", href=True):
        txt = " ".join(a.get_text(" ", strip=True).split())
        if not re.search(r"\(\s*\d{1,2}:\d{2}\s*\)", txt):
            continue

        m = re.match(r"^(.*?)\s*\(\s*(\d{1,2}:\d{2})\s*\)\s*(.*)$", txt)
        if not m:
            continue

        title = m.group(1).strip()
        start_time = m.group(2).strip()
        tail = (m.group(3) or "").strip()

        if not title:
            continue

        # Salong från svansen av titellänken
        venue = None
        m_sal = re.search(r"(salong\s*\d+)", tail, flags=re.IGNORECASE)
        if m_sal:
            venue = m_sal.group(1).strip().title()

        # Gå uppåt till närmaste container (div/li/article) för mer info
        container = a.find_parent(["div", "li", "article", "section"])
        if container is None:
            container = a.parent

        # Salong från containern om vi inte hittade i svansen
        if not venue and container:
            container_text = container.get_text(" ", strip=True)
            m_sal2 = re.search(r"(salong\s*\d+)", container_text, flags=re.IGNORECASE)
            if m_sal2:
                venue = m_sal2.group(1).strip().title()

        # Bokningslänk
        booking_url = None
        search_area = container if container else a.parent
        if search_area:
            for link in search_area.find_all("a", href=True):
                if "köp biljetter" in link.get_text(" ", strip=True).lower():
                    booking_url = urljoin(BASE_URL, link["href"])
                    break

        # Format-info (t.ex. "Dine-inSV tal | SV text")
        format_info = None
        if search_area:
            lines = [" ".join(x.split()) for x in search_area.get_text("\n", strip=True).splitlines()]
            for line in lines:
                if line.startswith(start_time):
                    rest = line[len(start_time):].strip()
                    if rest:
                        format_info = rest
                    break

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
    """
    Hämtar visningar för ett specifikt datum via /filmer?datum=YYYY-MM-DD.
    Sajten server-renderar innehållet för valt datum, så vi behöver
    inte JavaScript — bara skicka rätt query-parameter.
    """
    wanted = date.fromisoformat(target_date)
    url = f"{FILMER_URL}?datum={wanted.isoformat()}"
    html = _fetch_html(url, timeout=timeout)
    return _parse_showings(html, wanted)
