from __future__ import annotations
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from .common import abs_url, clean_spaces, get_html, parse_hhmm

URL = "https://www.reflexen.nu/program"

SV_MONTHS = {
    "januari": 1, "februari": 2, "mars": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "augusti": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}

# Matchar datum-rubriker som "12 april", "02 maj"
_RE_DATE_HEADER = re.compile(r"^\s*(\d{1,2})\s+([a-zåäö]+)\s*$", re.IGNORECASE)

# Bokningslänk med datum: /20260412/1300/
_RE_BOOKING_DATE = re.compile(r"/(\d{8})/(\d{4})/")


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Stockholm")).date()


def _header_to_iso(text: str) -> str | None:
    """Konvertera '12 april' → '2026-04-12'."""
    m = _RE_DATE_HEADER.match(text.strip())
    if not m:
        return None
    day = int(m.group(1))
    month = SV_MONTHS.get(m.group(2).lower())
    if not month:
        return None

    today = _today()
    year = today.year
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    if d < today - timedelta(days=30):
        d = date(year + 1, month, day)
    return d.isoformat()


def _booking_to_iso(booking_url: str) -> str | None:
    """Plocka ut datum från bokningslänk: /20260412/1300/ → '2026-04-12'."""
    m = _RE_BOOKING_DATE.search(booking_url or "")
    if not m:
        return None
    ymd = m.group(1)
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def _extract_format(title: str) -> tuple[str, str | None]:
    """Plocka ut specialvisning (Filmstudion, skådespelarbesök) från titeln."""
    extras = []

    # "Filmstudion: Drömmar" → prefix
    if title.lower().startswith("filmstudion:") or title.lower().startswith("filmstudion "):
        parts = re.split(r":\s*", title, maxsplit=1)
        if len(parts) == 2:
            extras.append("Filmstudion")
            title = parts[1].strip()

    # "Biodlaren + skådespelarbesök!" → suffix
    if "+" in title:
        parts = title.split("+", 1)
        base = parts[0].strip()
        extra = parts[1].strip().rstrip("!").strip()
        if extra and base:
            extras.append(extra)
            title = base

    return title, (", ".join(extras) if extras else None)


def fetch_reflexen(target_date: str, timeout: int = 20):
    html = get_html(URL, timeout=timeout)
    soup = BeautifulSoup(html, "html.parser")

    out = []
    seen = set()

    # Strategi: iterera genom alla element i dokumentordning, håll koll på
    # senaste datum-rubrik, och plocka upp alla "kl HH:MM" på rätt datum.
    current_date: str | None = None

    # Vi jobbar med alla textnoder och länkar i ordning
    for el in soup.find_all(string=True):
        text = clean_spaces(str(el))
        if not text:
            continue

        # Är det en datumrubrik?
        iso = _header_to_iso(text)
        if iso:
            current_date = iso
            continue

        if current_date != target_date:
            continue

        # Kolla om närmaste <a>-förälder är en "kl HH:MM"-länk
        parent = el.parent
        if not parent or parent.name != "a":
            continue
        if not text.lower().startswith("kl "):
            continue

        hhmm = parse_hhmm(text)
        if not hhmm:
            continue

        time_link = parent
        booking_href = time_link.get("href", "")

        # Dubbelcheck: om länken har ett datum i sig, ska det matcha
        booking_date = _booking_to_iso(booking_href)
        if booking_date and booking_date != target_date:
            continue

        # Titel-länken är nästa <a>-syskon
        title_el = time_link.find_next_sibling("a")
        if title_el is None:
            # Fallback: leta framåt i dokumentet
            title_el = time_link.find_next("a")
        if title_el is None:
            continue

        title = clean_spaces(title_el.get_text(" ", strip=True))
        title = title.rstrip(" -·")
        if not title:
            continue

        title, fmt = _extract_format(title)

        booking_url = abs_url(URL, booking_href) if booking_href and booking_href != "#" else None
        if not booking_url:
            # Filmstudion har ingen publik bokning — länka till filmsidan
            booking_url = abs_url(URL, title_el.get("href", ""))

        key = (hhmm, title, target_date)
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "title": title,
            "cinema": "Reflexen",
            "start_time": hhmm,
            "date": target_date,
            "booking_url": booking_url,
            "format_info": fmt,
            "district": "Kärrtorp",
            "venue": None,
            "source": URL,
            "category": "film",
        })

    return out
