# scrapers/kulturhuset.py
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import requests

ELASTIC_URL = "https://elastic.kulturhusetstadsteatern.se/khst-events/_search"
ELASTIC_AUTH = ("elastic", "elastic")

# drupalCategory id "6" = Bio
BIO_CATEGORY_ID = "6"


def _query_for_date(target: date) -> dict:
    """
    Bygger en Elasticsearch-query som hämtar alla bio-event
    (drupalCategory.id = "6") för ett specifikt datum.
    """
    day_start = f"{target.isoformat()}T00:00:00"
    day_end = f"{target.isoformat()}T23:59:59"

    return {
        "query": {
            "bool": {
                "must": [
                    {"range": {"tixStartDate": {"gte": day_start}}},
                    {"range": {"tixStartDate": {"lte": day_end}}},
                ],
                "filter": [
                    {
                        "nested": {
                            "path": "drupalCategory",
                            "query": {
                                "bool": {
                                    "filter": [
                                        {
                                            "terms": {
                                                "drupalCategory.id.keyword": [
                                                    BIO_CATEGORY_ID
                                                ]
                                            }
                                        }
                                    ]
                                }
                            },
                        }
                    }
                ],
            }
        },
        "sort": [{"tixStartDate": {"order": "asc"}}],
        "size": 200,
    }


def _parse_hit(hit: dict, wanted: date) -> dict[str, Any]:
    """Omvandlar ett Elasticsearch-hit till samma format som övriga scrapers."""
    src = hit["_source"]

    # Tid: "2026-03-15T18:00:00+01:00" → "18:00"
    start_raw = src.get("tixStartDate", "")
    try:
        dt = datetime.fromisoformat(start_raw)
        start_time = dt.strftime("%H:%M")
    except (ValueError, TypeError):
        start_time = ""

    title = src.get("drupalTitle", src.get("tixName", "")).strip()

    # Salong / venue
    hall_label = None
    if src.get("tixHall"):
        hall_label = src["tixHall"][0].get("label")

    venue_label = None
    if src.get("tixVenue"):
        venue_label = src["tixVenue"][0].get("label")

    # Cinema-namn baserat på salong/venue
    cinema = "Kulturhuset"
    if hall_label:
        if "klarabiografen" in hall_label.lower():
            cinema = "Klarabiografen"
        elif "skäris" in hall_label.lower() or "skarisbiografen" in hall_label.lower():
            cinema = "Skärisbiografen"
        elif "husby" in hall_label.lower():
            cinema = "Bio Husby"
        else:
            cinema = hall_label

    # Bokningslänk
    booking_url = src.get("tixTicketLink") or src.get("drupalLink")

    # Format-info: sammanfoga duration + eventuella notices
    parts = []
    if src.get("tixDuration"):
        parts.append(src["tixDuration"])
    if src.get("tixNotice"):
        parts.extend(src["tixNotice"])
    format_info = " | ".join(parts) if parts else None

    return {
        "title": title,
        "cinema": cinema,
        "start_time": start_time,
        "date": wanted.isoformat(),
        "booking_url": booking_url,
        "format_info": format_info,
        "venue": hall_label,
        "district": venue_label,
        "source": "kulturhusetstadsteatern.se",
        "category": "film",
    }


def fetch_kulturhuset(target_date: str, timeout: int = 20) -> list[dict[str, Any]]:
    """
    Hämtar filmvisningar (bio) från Kulturhuset Stadsteatern
    via deras Elasticsearch-API.
    """
    wanted = date.fromisoformat(target_date)
    query = _query_for_date(wanted)

    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": "https://kulturhusetstadsteatern.se",
        "Referer": "https://kulturhusetstadsteatern.se/",
    }

    r = requests.post(
        ELASTIC_URL,
        json=query,
        auth=ELASTIC_AUTH,
        headers=headers,
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()

    hits = data.get("hits", {}).get("hits", [])

    rows = [_parse_hit(h, wanted) for h in hits]

    # Filtrera bort tomma titlar
    rows = [r for r in rows if r["title"]]

    # Dedup
    seen = set()
    uniq: list[dict[str, Any]] = []
    for row in rows:
        k = (row["date"], row["start_time"], row["title"].lower(), row.get("venue"))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(row)

    return uniq
