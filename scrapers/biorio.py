from __future__ import annotations
import re
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from .common import abs_url, clean_spaces, get_html, parse_hhmm

URL = "https://www.biorio.se/sv/kalender"

SV_MONTHS = {
    "januari": 1, "februari": 2, "mars": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "augusti": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}

SPECIAL_TAGS = (
    "Barnvagnsbio", "Frukostbio", "Bakisbio", "Hundbio", "Members Only",
    "Förhandsvisning", "Smygpremiär", "Family Time", "Rendez-Vous",
    "Med besök", "Slutsåld",
)


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Stockholm")).date()


def _header_to_iso(header_text: str) -> str | None:
    """Konvertera 'Idag 7 april', 'Imorgon 8 april', 'Torsdag 9 april' → ISO."""
    text = clean_spaces(header_text).lower()
    today = _today()

    if text.startswith("idag"):
        return today.isoformat()
    if text.startswith("imorgon") or text.startswith("i morgon"):
        return (today + timedelta(days=1)).isoformat()

    m = re.search(r"(\d{1,2})\s+([a-zåäö]+)", text)
    if not m:
        return None
    day = int(m.group(1))
    month = SV_MONTHS.get(m.group(2))
    if not month:
        return None

    year = today.year
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    if d < today - timedelta(days=30):
        d = date(year + 1, month, day)
    return d.isoformat()


def _parse_item(item_div, target_date: str) -> dict | None:
    """Tolka en .kalender-showtime-item och returnera en visningsdict."""
    text = clean_spaces(item_div.get_text(" ", strip=True))
    # Exempel: "10:00 The Drama Salong 1 · 105 min Barnvagnsbio"

    hhmm = parse_hhmm(text)
    if not hhmm:
        return None

    # Hitta bokningslänken
    link = item_div.find("a", href=lambda h: h and "/boka/" in h)
    booking_url = abs_url(URL, link.get("href")) if link else None

    # Plocka ut salong
    venue_match = re.search(r"Salong\s*\d+", text)
    venue = venue_match.group(0) if venue_match else "Salong 1"

    # Plocka ut titel: allt mellan tiden och "Salong N"
    title = re.sub(r"^\s*\d{1,2}[:.]\d{2}\s*", "", text)
    if venue_match:
        title = title[:title.find(venue_match.group(0))].strip()
    title = title.strip(" ·-")
    if not title:
        return None

    # Specialvisningstaggar
    extras = [tag for tag in SPECIAL_TAGS if tag in text]
    format_info = ", ".join(extras) if extras else None

    return {
        "title": title,
        "cinema": "Bio Rio",
        "start_time": hhmm,
        "date": target_date,
        "booking_url": booking_url,
        "format_info": format_info,
        "district": "Södermalm",
        "venue": venue,
        "source": URL,
        "category": "film",
    }


def fetch_biorio(target_date: str, timeout: int = 20):
    html = get_html(URL, timeout=timeout)
    soup = BeautifulSoup(html, "html.parser")

    out = []
    seen = set()

    # Varje dag har en egen .kalender-day-group med en <h2> överst
    for day_group in soup.select(".kalender-day-group"):
        h2 = day_group.find(["h2", "h3"])
        if not h2:
            continue
        iso = _header_to_iso(h2.get_text(" ", strip=True))
        if iso != target_date:
            continue

        for item in day_group.select(".kalender-showtime-item"):
            row = _parse_item(item, target_date)
            if not row:
                continue
            key = row.get("booking_url") or (row["title"], row["start_time"])
            if key in seen:
                continue
            seen.add(key)
            out.append(row)

        break  # rätt dag hittad

    return out
