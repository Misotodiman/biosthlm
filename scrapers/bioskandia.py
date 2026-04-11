# scrapers/bioskandia.py
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests

STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")

SHOWTIMES_URL = "https://bioskandia.se/wp-json/skandia/v1/showtimes"
BASE_HOST = "https://bioskandia.se"

USER_AGENT = "bioschema/1.0 (+https://example.com) python-requests"


def _http_get_json(url: str, timeout: int) -> Any:
    r = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.7",
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def _coerce_target_date(target_date: str | date | None) -> date:
    if target_date is None:
        return datetime.now(STOCKHOLM_TZ).date()
    if isinstance(target_date, date):
        return target_date
    # main.py skickar ISO-sträng
    return date.fromisoformat(target_date)


def _abs_booking_url(booking_url: Optional[str]) -> Optional[str]:
    if not booking_url:
        return None
    u = str(booking_url).strip()
    if not u:
        return None
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if u.startswith("/"):
        return BASE_HOST + u
    return BASE_HOST + "/" + u.lstrip("/")


def fetch_bioskandia(
    *,
    target_date: str | date | None = None,
    timeout: int = 20,
    **_kwargs,
) -> list[dict]:
    """
    Skandia via WP JSON:
      https://bioskandia.se/wp-json/skandia/v1/showtimes

    show_times_by_day:
      data.show_times_by_day["YYYY-MM-DD"] -> list av showtimes

    Returnerar dictar kompatibla med main.py/Show:
      title, cinema, start_time, date, booking_url, format_info, district, venue, source, category
    """
    td = _coerce_target_date(target_date)
    td_iso = td.isoformat()

    payload = _http_get_json(SHOWTIMES_URL, timeout=timeout)

    by_day = (
        (payload or {})
        .get("data", {})
        .get("show_times_by_day", {})
    )

    items = by_day.get(td_iso, []) if isinstance(by_day, dict) else []
    if not isinstance(items, list):
        items = []

    rows: list[dict] = []
    seen: set[tuple] = set()

    for st in items:
        if not isinstance(st, dict):
            continue

        title = (st.get("title") or "").strip()
        start_time = (st.get("time") or "").strip()
        booking_url = _abs_booking_url(st.get("booking_url"))

        if not title or not start_time:
            continue

        # format_info: komprimera språk/subs/duration (valfritt men nyttigt)
        language = st.get("language")
        subtitles = st.get("subtitles")
        duration = st.get("duration")
        fmt_parts = []
        if language:
            fmt_parts.append(str(language))
        if subtitles:
            fmt_parts.append(f"subs: {subtitles}")
        if duration:
            fmt_parts.append(f"{duration} min")
        format_info = " | ".join(fmt_parts) if fmt_parts else None

        key = (td_iso, start_time, title, booking_url or "")
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            {
                "title": title,
                "cinema": "Bio Skandia",
                "start_time": start_time,
                "date": td_iso,
                "booking_url": booking_url,
                "format_info": format_info,
                "district": "Norrmalm",
                "venue": None,
                "source": "bioskandia.se/wp-json/skandia/v1/showtimes",
                "category": "film",
            }
        )

    return sorted(rows, key=lambda r: r["start_time"])
