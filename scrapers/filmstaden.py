from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any
import requests

SHOW_URL = "https://services.cinema-api.com/show/stripped/sv/1/1024?filter.countryAlias=se&filter.cityAlias=SE&filter.channel=App"
MOVIE_URL = "https://services.cinema-api.com/movie/sv"
MOBILE_BASE = "https://mobile.filmstaden.se/biljetter/se/"
FILMSTADEN_FILM_BASE = "https://www.filmstaden.se/film/"

STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")


def _build_film_url(slug: str | None) -> str:
    """Bygg URL till filmens sida på filmstaden.se där alla visningar listas."""
    if slug and isinstance(slug, str):
        return f"{FILMSTADEN_FILM_BASE}{slug}/"
    return MOBILE_BASE


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://mobile.filmstaden.se",
        "Referer": "https://mobile.filmstaden.se/",
    })
    return s


def _chunks(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _playwright_fetch_json(url: str, timeout: int = 30) -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError(
            "Filmstaden API kräver browser-session här. Installera Playwright: pip install playwright && python -m playwright install chromium"
        ) from e

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="sv-SE")
        page = ctx.new_page()

        # Öppna mobile-sidan först så requests sker från rätt origin/session
        page.goto(MOBILE_BASE, wait_until="domcontentloaded", timeout=timeout * 1000)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        # Fetch inne i browsern (använder cookies/session från context)
        result = page.evaluate(
            """async (url) => {
                const r = await fetch(url, {
                  method: 'GET',
                  credentials: 'include',
                  headers: {
                    'Accept': 'application/json, text/plain, */*'
                  }
                });
                const text = await r.text();
                return {
                  ok: r.ok,
                  status: r.status,
                  statusText: r.statusText,
                  text
                };
            }""",
            url
        )
        browser.close()

    if not result.get("ok"):
        raise RuntimeError(f"Filmstaden API via Playwright fetch misslyckades: {result.get('status')} {result.get('statusText')}")

    import json
    return json.loads(result["text"])


def _fetch_showtimes(timeout: int = 20) -> list[dict[str, Any]]:
    # Försök requests först (snabbt), fallback till Playwright browser-fetch vid 403
    s = _session()
    try:
        r = s.get(SHOW_URL, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return data.get("items", []) if isinstance(data, dict) else []
    except requests.HTTPError as e:
        if getattr(e.response, "status_code", None) != 403:
            raise

    data = _playwright_fetch_json(SHOW_URL, timeout=max(timeout, 30))
    return data.get("items", []) if isinstance(data, dict) else []


def _fetch_movies_by_ids(movie_ids: list[str], timeout: int = 20) -> dict[str, dict[str, Any]]:
    """
    Mapping:
      version_ncg_id (NCGxxxxxxVn) -> metadata
      "__base__:<mId>" -> fallbacktitel
    """
    out: dict[str, dict[str, Any]] = {}
    if not movie_ids:
        return out

    s = _session()

    for batch in _chunks(movie_ids, 25):
        params = {"movieNcgIds": ",".join(batch)}
        try:
            r = s.get(MOVIE_URL, params=params, timeout=timeout)
            r.raise_for_status()
            payload = r.json()
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", None) != 403:
                raise
            # bygg URL och hämta via browser-fetch
            from urllib.parse import urlencode
            payload = _playwright_fetch_json(f"{MOVIE_URL}?{urlencode(params)}", timeout=max(timeout, 30))

        items = payload.get("items", []) if isinstance(payload, dict) else []

        for item in items:
            versions = item.get("versions") or []
            base_id = None

            for k in ("ncgId", "mId", "movieNcgId"):
                if isinstance(item.get(k), str):
                    base_id = item[k]
                    break

            first_title = None

            for v in versions:
                v_ncg = v.get("ncgId")
                v_title = v.get("title")
                if isinstance(v_title, str) and v_title and not first_title:
                    first_title = v_title
                if isinstance(v_ncg, str) and v_ncg:
                    out[v_ncg] = {
                        "title": v_title or "",
                        "slug": v.get("slug"),
                        "rating": ((v.get("rating") or {}).get("displayName") if isinstance(v.get("rating"), dict) else None),
                        "audioLanguage": ((v.get("audioLanguageInfo") or {}).get("displayName") if isinstance(v.get("audioLanguageInfo"), dict) else None),
                        "subtitlesLanguage": ((v.get("subtitlesLanguageInfo") or {}).get("displayName") if isinstance(v.get("subtitlesLanguageInfo"), dict) else None),
                        "attributes": [a.get("displayName") for a in (v.get("attributes") or []) if isinstance(a, dict) and a.get("displayName")],
                    }

            if not base_id and versions:
                for v in versions:
                    v_ncg = v.get("ncgId")
                    if isinstance(v_ncg, str) and "V" in v_ncg:
                        base_id = v_ncg.split("V", 1)[0]
                        break

            if base_id and first_title:
                out[f"__base__:{base_id}"] = {"title": first_title}

    return out


def _utc_to_stockholm(utc_str: str) -> tuple[str, str] | None:
    if not utc_str:
        return None
    try:
        if utc_str.endswith("Z"):
            dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(utc_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(STOCKHOLM_TZ)
        return local.date().isoformat(), local.strftime("%H:%M")
    except Exception:
        return None


def _title_for_show(show: dict[str, Any], movie_map: dict[str, dict[str, Any]]) -> str:
    mv_id = show.get("mvId")
    m_id = show.get("mId")

    if isinstance(mv_id, str) and mv_id in movie_map:
        t = movie_map[mv_id].get("title")
        if t:
            return t

    if isinstance(m_id, str):
        fb = movie_map.get(f"__base__:{m_id}")
        if fb and fb.get("title"):
            return fb["title"]

        prefix = m_id + "V"
        for k, v in movie_map.items():
            if k.startswith(prefix) and v.get("title"):
                return v["title"]

    return f"Film {m_id or ''}".strip()


def _format_info_for_show(show: dict[str, Any], movie_map: dict[str, dict[str, Any]]) -> str | None:
    parts: list[str] = []

    sa = show.get("sa")
    if isinstance(sa, list) and sa:
        parts.extend(str(x) for x in sa if x)

    mv_id = show.get("mvId")
    meta = movie_map.get(mv_id) if isinstance(mv_id, str) else None
    if isinstance(meta, dict):
        attrs = meta.get("attributes") or []
        if isinstance(attrs, list):
            for a in attrs[:3]:
                if a and a not in parts:
                    parts.append(str(a))

    venue = show.get("st")
    if isinstance(venue, str) and venue and venue not in parts:
        parts.append(venue)

    if not parts:
        return None
    return " · ".join(parts)


def fetch_filmstaden_stockholm_stub(target_date: str, timeout: int = 20):
    shows = _fetch_showtimes(timeout=timeout)

    prelim: list[dict[str, Any]] = []
    movie_ids: set[str] = set()

    for sh in shows:
        if not isinstance(sh, dict):
            continue
        utc = sh.get("utc")
        conv = _utc_to_stockholm(utc) if isinstance(utc, str) else None
        if not conv:
            continue

        local_date, local_time = conv
        if local_date != target_date:
            continue

        prelim.append({"_raw": sh, "date": local_date, "start_time": local_time})

        m_id = sh.get("mId")
        if isinstance(m_id, str) and m_id:
            movie_ids.add(m_id)

    movie_map = _fetch_movies_by_ids(sorted(movie_ids), timeout=timeout)

    rows: list[dict[str, Any]] = []
    seen = set()

    for item in prelim:
        sh = item["_raw"]
        cinema = sh.get("ct") or "Filmstaden"
        title = _title_for_show(sh, movie_map)
        start_time = item["start_time"]

        # Hitta filmens slug så vi kan länka till rätt filmsida
        slug = None
        mv_id = sh.get("mvId")
        if isinstance(mv_id, str):
            meta = movie_map.get(mv_id)
            if isinstance(meta, dict):
                slug = meta.get("slug")

        row = {
            "title": title,
            "cinema": str(cinema),
            "start_time": start_time,
            "date": item["date"],
            "booking_url": _build_film_url(slug),
            "format_info": _format_info_for_show(sh, movie_map),
            "district": None,
            "venue": str(sh.get("st")) if sh.get("st") else None,
            "source": "https://services.cinema-api.com/",
            "category": "film",
        }

        key = (row["title"], row["cinema"], row["start_time"], row["venue"] or "")
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)

    rows.sort(key=lambda r: (r["start_time"], r["cinema"].lower(), r["title"].lower()))
    return rows