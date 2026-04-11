from __future__ import annotations

from typing import Any
import requests


API_URL = "https://zita.se/api/get-kalendarium-week.php"


def _get_json(timeout: int) -> dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; bio-schema-stockholm/1.0; +https://example.invalid)",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
        "Referer": "https://zita.se/start",
    }
    r = requests.get(API_URL, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _hhmm(ctime: str | None) -> str | None:
    if not ctime:
        return None
    # "12:00:00" -> "12:00"
    s = ctime.strip()
    if len(s) >= 5 and s[2] == ":":
        return s[:5]
    return s


def _format_info(event_obj: dict[str, Any], showing_obj: dict[str, Any]) -> str | None:
    parts: list[str] = []

    # "event" kan vara t.ex. "Zita Barnens Bio"
    if event_obj.get("event"):
        parts.append(str(event_obj["event"]).strip())

    # genre/language/subtitles är ofta ifyllda
    for k in ("genre", "language", "subtitles"):
        v = event_obj.get(k)
        if v:
            vv = str(v).strip()
            if vv and vv.lower() not in {"ej angivet"}:
                parts.append(vv)

    # special_message kan vara t.ex. "Kort tid kvar!" eller "2 för 1"
    sm = showing_obj.get("special_message")
    if sm:
        sm = str(sm).strip()
        if sm:
            parts.append(sm)

    # message ibland
    msg = showing_obj.get("message")
    if msg:
        msg = str(msg).strip()
        if msg:
            parts.append(msg)

    if not parts:
        return None

    # håll format_info kompakt och stabilt
    return " | ".join(dict.fromkeys(parts))


def fetch_zita(target_date: str, timeout: int = 20):
    """
    Returnerar list[dict] med keys som matchar Show i main.py:
    title, cinema, start_time, date, booking_url, format_info, district, venue, source, category
    """
    data = _get_json(timeout=timeout)
    week_events = data.get("week_events") or {}
    day_events = week_events.get(target_date) or []

    rows: list[dict[str, Any]] = []

    for ev in day_events:
        title = (ev.get("title") or "").strip()
        showings = ev.get("showings") or []
        for sh in showings:
            start_time = _hhmm(sh.get("ctime"))
            if not start_time:
                continue

            screen = (sh.get("screen_name") or "").strip()
            venue = f"Salong {screen}" if screen else None

            rows.append({
                "title": title,
                "cinema": "Zita",
                "start_time": start_time,
                "date": target_date,
                "booking_url": sh.get("booking_url"),
                "format_info": _format_info(ev, sh),
                "district": None,
                "venue": venue,
                "source": "zita.se/api/get-kalendarium-week.php",
                "category": "film",
            })

    # Dedup: (date, time, title, venue)
    seen = set()
    uniq = []
    for r in rows:
        k = (
            r["date"],
            r["start_time"],
            (r["title"] or "").strip().lower(),
            r.get("venue"),
        )
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    return uniq
