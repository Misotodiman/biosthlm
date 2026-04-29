from __future__ import annotations
import argparse
import base64
import os
import re
import sys
import json
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, date
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scrapers.biofagelbla import fetch_biofagelbla
from scrapers.biorio import fetch_biorio
from scrapers.cinemateket import fetch_cinemateket
from scrapers.filmstaden import fetch_filmstaden_stockholm_stub
from scrapers.bioaspen import fetch_bioaspen
from scrapers.capitol import fetch_capitol
from scrapers.tellus import fetch_tellus
from scrapers.zita import fetch_zita
from scrapers.bioskandia import fetch_bioskandia
from scrapers.kulturhuset import fetch_kulturhuset
from scrapers.biobristol import fetch_biobristol
from scrapers.reflexen import fetch_reflexen


STOCKHOLM_TZ = ZoneInfo("Europe/Stockholm")

DEFAULT_HIDDEN_CINEMAS = {
    "Filmstaden Täby",
    "Filmstaden Sickla",
    "Filmstaden Scandinavia",
    "Filmstaden Heron City",
    "Filmstaden Vällingby",
    "Filmstaden Kista",
    "Grand Lidingö",
}


@dataclass
class Show:
    title: str
    cinema: str
    start_time: str
    date: str
    booking_url: str | None = None
    format_info: str | None = None
    district: str | None = None
    venue: str | None = None
    source: str | None = None
    category: str = "film"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--start-date")
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--include-filmstaden", action="store_true")
    p.add_argument("--no-history", action="store_true")
    return p.parse_args()


def today_stockholm() -> date:
    return datetime.now(STOCKHOLM_TZ).date()


def iter_dates(start: str | None, days: int):
    d0 = date.fromisoformat(start) if start else today_stockholm()
    for i in range(days):
        yield (d0 + timedelta(days=i)).isoformat()


def norm_title(s: str) -> str:
    return " ".join((s or "").split()).strip().lower()


def sort_key(s: Show):
    return (s.date, s.start_time or "99:99", norm_title(s.title), (s.cinema or "").lower())


def pretty_sv_date(iso_date: str) -> str:
    d = date.fromisoformat(iso_date)
    wd = ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag"][d.weekday()]
    mo = [
        "januari", "februari", "mars", "april", "maj", "juni",
        "juli", "augusti", "september", "oktober", "november", "december"
    ][d.month - 1]
    return f"{wd} {d.day} {mo}"


# ── TITLE NORMALIZATION ──────────────────────────────────────────────
#
# Mål: "The Housemaid - VIP", "The Housemaid iSense", "The Housemaid - Rigoletto"
#       → alla blir titel "The Housemaid" med formatet i format_info.
#
# Strategi (framtidssäker):
#   1. Regex-mönster för kända strukturer (språktaggar, formatord).
#   2. Korsreferens: om "Film X" finns som egen titel OCH "Film X - Hundbio"
#      finns → "Hundbio" är ett format, även om vi aldrig sett det förut.
#   3. Fuzzy dedup: "TOMMY TASS" vs "Tommy Tass", "Vi passar ihop!" vs
#      "Vi passar ihop" slås ihop till den vanligaste stavningen.
#
# Kända format/plats-nyckelord (gemener, utan ® etc.)
_FORMAT_KEYWORDS: set[str] = {
    "imax", "isense", "vip", "3d", "70mm", "35mm", "dcp",
    "rigoletto",   # Filmstaden Rigoletto-salongen
    "dolby", "atmos", "laser", "screenx",
    "project hail mary",  # lägg inte till – det här är bara en kommentar :)
}
# Ta bort den skojiga raden ovan ifall den hamnar kvar
_FORMAT_KEYWORDS.discard("project hail mary")

# Kända event-/visningstypsprefix (gemener)
_EVENT_PREFIXES: set[str] = {
    "afternoon tea", "stickbio", "unga cinemateket", "autismvänlig",
    "barnvagnsbio", "bebisvänlig", "seniorvisning", "skolvisning",
    "babybio", "hundvisning", "seniorbio",
}

# Språktaggar i parentes: (sv tal), (eng text), (sve tal), etc.
_RE_LANG = re.compile(
    r"\s*\(\s*(?:sv|sve|eng|sv\.|eng\.)\s+(?:tal|text|dubb)\s*\)",
    re.IGNORECASE,
)

# Lösa formatord i slutet utan separator: "Film iSense", "Film 3D"
_RE_TRAILING_FMT = re.compile(
    r"\s+(iSense|VIP|IMAX®?|3D|70mm|35mm)\s*$",
    re.IGNORECASE,
)


def _canon_key(title: str) -> str:
    """Skapa en normaliseringsnyckel för fuzzy-jämförelse.

    Gemener, utan diakritiska tecken och skiljetecken.
    'Sirât' och 'Sirāt' → samma nyckel.
    """
    s = unicodedata.normalize("NFKD", title)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", "", s)
    return " ".join(s.lower().split())


def normalize_shows(shows: list[Show]) -> list[Show]:
    """Normalisera filmtitlar och flytta format/visningstyp till format_info.

    Framtidssäker via korsreferens mot alla råtitlar i datasetet.
    """

    # Samla alla råtitlar (gemener) för korsreferens
    raw_lower: set[str] = {s.title.strip().lower() for s in shows}

    for show in shows:
        title = show.title.strip()
        extras: list[str] = []

        # Behåll befintlig format_info
        if show.format_info:
            extras.append(show.format_info)

        # ── 1. Språktaggar: "(sv tal)", "(eng text)" ──
        lang_match = _RE_LANG.search(title)
        if lang_match:
            tag = lang_match.group(0).strip().strip("()")
            extras.append(tag)
            title = _RE_LANG.sub("", title).strip()

        # ── 2. Suffix efter sista " - " ──
        # "The Housemaid - VIP"  → titel "The Housemaid", format "VIP"
        # "Goat - bäst i världen" → inget strippas (del av titeln)
        dash_idx = title.rfind(" - ")
        if dash_idx > 0:
            base = title[:dash_idx].strip()
            suffix = title[dash_idx + 3:].strip()
            suffix_clean = re.sub(r"[®™]", "", suffix).strip().lower()

            # Strippa om: (a) suffixet är ett känt format, ELLER
            #              (b) suffixet är kort (≤3 ord) och bastitel finns
            #                  bland de andra filmerna
            if (suffix_clean in _FORMAT_KEYWORDS
                    or (len(suffix.split()) <= 3
                        and base.lower() in raw_lower)):
                extras.append(suffix)
                title = base

        # ── 3. Lösa formatord i slutet: "Film iSense" ──
        trail_match = _RE_TRAILING_FMT.search(title)
        if trail_match:
            extras.append(trail_match.group(1))
            title = title[: trail_match.start()].strip()

        # ── 4. Event-prefix före ": " ──
        # "Afternoon Tea: Downton Abbey" → "Downton Abbey", format "Afternoon Tea"
        # "Kill Bill: The Whole Bloody Affair" → behålls (inte ett event-prefix)
        colon_idx = title.find(": ")
        if colon_idx > 0:
            prefix = title[:colon_idx].strip()
            remainder = title[colon_idx + 2:].strip()

            if (prefix.lower() in _EVENT_PREFIXES
                    or remainder.lower() in raw_lower):
                extras.append(prefix)
                title = remainder

        # ── 5. Event-prefix före " - " ──
        # "Autismvänlig - Skurkarnas Skurk" → "Skurkarnas Skurk"
        dash_idx2 = title.find(" - ")
        if dash_idx2 > 0:
            prefix2 = title[:dash_idx2].strip()
            remainder2 = title[dash_idx2 + 3:].strip()

            if prefix2.lower() in _EVENT_PREFIXES:
                extras.append(prefix2)
                title = remainder2
            elif (len(prefix2.split()) <= 2
                  and remainder2.lower() in raw_lower):
                # Okänt prefix, men filmen finns som egen titel → troligt event
                extras.append(prefix2)
                title = remainder2

        # Uppdatera show
        show.title = title.strip()
        combined = ", ".join(filter(None, extras))
        show.format_info = combined if combined else None

    # ── Fuzzy dedup: slå ihop nästan-identiska titlar ──
    # "TOMMY TASS får en ny vän" / "Tommy Tass får en ny vän" → samma
    # "Vi passar ihop!" / "Vi passar ihop" → samma
    # "Sirât" / "Sirāt" → samma
    canon_groups: dict[str, list[Show]] = {}
    for show in shows:
        key = _canon_key(show.title)
        canon_groups.setdefault(key, []).append(show)

    for group in canon_groups.values():
        if len(group) < 2:
            continue
        # Välj den vanligaste stavningen som kanonisk titel
        counts = Counter(s.title for s in group)
        canonical = counts.most_common(1)[0][0]
        for s in group:
            s.title = canonical

    print(f"[NORM] Normaliserade {len(shows)} visningar → "
          f"{len({s.title for s in shows})} unika titlar")
    return shows


# ── FORMAT/VENUE CLEANUP ─────────────────────────────────────────────
#
# Mål: städa upp format_info och venue så att irrelevant skräp tas bort
# (ljudformat, syntolkning, dubblerade salongnamn, pris, etc.) men
# behåll meningsfull info (IMAX, VIP, sv tal, specialvisningar).

# Saker som ska BORT från format_info helt
_FMT_DROP_EXACT = {
    # Ljudformat
    "5.1", "7.1", "dolby", "dolby atmos", "atmos", "laser",
    # Tillgänglighet
    "syntolkning via app", "syntolkning", "uppläst text",
    # Filmstaden-skräp
    "familj", "isense", "biopasset 5", "biopasset",
    "xl - vår största duk", "xl",
    # Bristol-skräp
    "vf",
    # Zita-skräp
    "array",
    # Generella språknamn (vi behåller "sv tal" / "eng tal" istället)
    "svenska", "svenska (dubbat)", "engelska",
}

# Det här SKA behållas (whitelist för att vara extra säker)
_FMT_KEEP_PATTERNS = (
    "imax", "vip", "3d", "70mm", "35mm",
    "sv tal", "eng tal", "sv. tal", "eng. tal", "sve tal",
    "rigoletto",  # Filmstaden Rigoletto är en specialsalong
    # Specialvisningar
    "barnvagnsbio", "frukostbio", "bakisbio", "hundbio",
    "members only", "förhandsvisning", "smygpremiär",
    "family time", "rendez-vous", "med besök", "slutsåld",
    "stickbio", "filmstudion", "knattebio", "påsklovsbio",
    "seniorbio", "skolvisning", "skolbio",
    "regissörsbesök", "skådespelarbesök", "premiär",
    "autismvänlig", "afternoon tea", "unga cinemateket",
    "dine-in", "familjematiné",
)


def _is_salong(token: str) -> bool:
    """Kolla om en token är ett salongnamn (Salong N, Salong N VIP,
    IMAX®-salongen (Salong 1), VIP-salong, etc.)"""
    t = token.strip().lower()
    if t.startswith("salong"):
        return True
    if "salongen" in t and "(" in t:  # IMAX®-salongen (Salong 1)
        return True
    if t == "vip-salong":
        return False  # behåll detta som format-info, salongen står ändå i venue
    return False


def _should_drop(token: str) -> bool:
    """Avgör om en format-token ska kastas bort."""
    t = token.strip().lower()
    if not t:
        return True

    # Salongnamn ska bort (de finns redan i venue)
    if _is_salong(t):
        return True

    # Exakta matchningar
    if t in _FMT_DROP_EXACT:
        return True

    # Pris: "90 kr", "120 kronor"
    if re.match(r"^\d+\s*(kr|kronor|:-)\s*$", t):
        return True

    # Filmlängd ska bort härifrån (vi använder TMDB:s data istället)
    if re.match(r"^\d+\s*(min|minuter)\s*$", t):
        return True

    # Datum-mönster ("onsdag 15 april", "15 april kl 19.30")
    if re.match(r"^[a-zåäö]+\s+\d{1,2}\s+[a-zåäö]+", t):
        return True

    # "återkommande evenemang", "se alla one event", "(see all)"
    if "återkommande" in t or "one event" in t or "see all" in t:
        return True

    return False


def _looks_meaningful(token: str) -> bool:
    """Behåll bara format-tokens som är vettiga för användaren."""
    t = token.strip().lower()
    if not t:
        return False
    if _should_drop(t):
        return False
    # Whitelist-check
    for pattern in _FMT_KEEP_PATTERNS:
        if pattern in t:
            return True
    # Okänd token: behåll bara om den är kort och inte ser ut som skräp
    if len(t) <= 30 and not any(c in t for c in ("|", ";", "@", "{")):
        return True
    return False


def clean_format_info(shows: list[Show]) -> None:
    """Städa upp format_info-fältet för alla visningar."""
    for s in shows:
        # 1. Cinema-fältet: ta bort dubblering "Bio Rio · Bio Rio" → "Bio Rio"
        if s.cinema:
            parts = [p.strip() for p in re.split(r"[·|]", s.cinema)]
            unique_parts = []
            for p in parts:
                if p and p not in unique_parts:
                    unique_parts.append(p)
            s.cinema = " · ".join(unique_parts)

        # 2. Venue-fältet: om det är samma som cinema, sätt till None
        if s.venue and s.cinema and s.venue.strip().lower() == s.cinema.strip().lower():
            s.venue = None

        # 3. Format_info: dela upp på · | , och rensa
        if not s.format_info:
            continue

        raw = s.format_info
        # Splitta på vanliga separatorer
        tokens = re.split(r"\s*[·|]\s*|,\s+", raw)

        kept = []
        seen = set()
        for tok in tokens:
            tok = tok.strip(" ·-")
            if not tok:
                continue
            key = tok.lower()
            if key in seen:
                continue
            if not _looks_meaningful(tok):
                continue
            seen.add(key)
            # Normalisera vanliga varianter
            if key in ("sv tal", "sve tal", "sv. tal"):
                tok = "sv tal"
            elif key in ("eng tal", "eng. tal"):
                tok = "eng tal"
            kept.append(tok)

        s.format_info = ", ".join(kept) if kept else None


# ── TMDB POSTER LOOKUP ───────────────────────────────────────────────

TMDB_IMG_BASE = "https://image.tmdb.org/t/p/"
TMDB_THUMB_SIZE = "w92"      # liten thumbnail (92px bred)
TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"

# Rensa titlar innan TMDB-sökning
_RE_YEAR_SUFFIX = re.compile(r"\s*\((\d{4})\)\s*$")              # "Gökboet (1975)"
_RE_DIRECTOR_SUFFIX = re.compile(r",\s*[A-ZÅÄÖ][a-zåäöé]+.*$")  # ", Charlie Chaplin"


def _tmdb_query(query: str, token: str, language: str = "") -> dict | None:
    """Gör en TMDB-sökning, returnera första träffen eller None."""
    from urllib.parse import quote
    lang_param = f"&language={language}" if language else ""
    url = f"{TMDB_SEARCH_URL}?query={quote(query)}&page=1{lang_param}"
    req = Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except (URLError, OSError, json.JSONDecodeError):
        return None

    results = data.get("results", [])
    return results[0] if results else None


def _tmdb_get_runtime(movie_id: int, token: str) -> int | None:
    """Hämta filmlängd via TMDB movie details endpoint."""
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    req = Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        runtime = data.get("runtime")
        return runtime if runtime and runtime > 0 else None
    except (URLError, OSError, json.JSONDecodeError):
        return None


def _tmdb_search(title: str, token: str) -> dict | None:
    """Sök TMDB efter filmtitel med flera fallback-strategier.

    Returnerar dict med 'poster_url' och 'runtime' eller None.
    """
    # Rensa titeln
    clean = title.strip()

    # Ta bort årtal: "Gökboet (1975)" → "Gökboet"
    year_match = _RE_YEAR_SUFFIX.search(clean)
    if year_match:
        clean = clean[:year_match.start()].strip()

    # Ta bort regissörsnamn: "Moderna tider, Charlie Chaplin" → "Moderna tider"
    dir_match = _RE_DIRECTOR_SUFFIX.search(clean)
    if dir_match:
        clean = clean[:dir_match.start()].strip()

    queries = [clean]

    # Om titeln har " - " mitt i, prova bara första delen
    if " - " in clean:
        first_part = clean.split(" - ")[0].strip()
        if len(first_part) > 2:
            queries.append(first_part)

    for query in queries:
        for lang in ("sv-SE", ""):
            result = _tmdb_query(query, token, language=lang)
            if result and result.get("poster_path"):
                poster_url = f"{TMDB_IMG_BASE}{TMDB_THUMB_SIZE}{result['poster_path']}"
                movie_id = result.get("id")
                runtime = _tmdb_get_runtime(movie_id, token) if movie_id else None
                return {"poster_url": poster_url, "runtime": runtime}

    return None


def fetch_posters(shows: list[Show]) -> tuple[dict[str, str], dict[str, int]]:
    """Slå upp affisch-URL och filmlängd för varje unik filmtitel via TMDB.

    Returnerar (posters, runtimes):
      posters:  {titel: poster_url}
      runtimes: {titel: minuter}
    Kräver miljövariabeln TMDB_API_TOKEN.
    """
    token = os.environ.get("TMDB_API_TOKEN", "")
    if not token:
        print("[TMDB] Ingen TMDB_API_TOKEN satt — hoppar över affischer.")
        return {}, {}

    titles = sorted({s.title for s in shows if s.title})
    print(f"[TMDB] Slår upp affischer för {len(titles)} titlar…")

    posters: dict[str, str] = {}
    runtimes: dict[str, int] = {}

    # Läs cache om den finns (undvik onödiga API-anrop)
    # Cache-format: {titel: {"poster_url": "...", "runtime": 123} | null}
    cache_path = Path(__file__).parent / "output" / "poster_cache.json"
    cache: dict[str, dict | None] = {}
    if cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            # Migrera gammal cache (string-format) till nytt dict-format
            for k, v in raw.items():
                if isinstance(v, str):
                    cache[k] = {"poster_url": v, "runtime": None}
                else:
                    cache[k] = v
        except Exception:
            cache = {}

    hits = misses = 0
    for title in titles:
        if title in cache:
            entry = cache[title]
            if entry and entry.get("poster_url"):
                posters[title] = entry["poster_url"]
                if entry.get("runtime"):
                    runtimes[title] = entry["runtime"]
            hits += 1
            continue

        result = _tmdb_search(title, token)
        if result:
            cache[title] = result
            posters[title] = result["poster_url"]
            if result.get("runtime"):
                runtimes[title] = result["runtime"]
            misses += 1
            rt_str = f" ({result['runtime']} min)" if result.get("runtime") else ""
            print(f"  [TMDB] ✓ {title}{rt_str}")
        else:
            cache[title] = None
            misses += 1
            print(f"  [TMDB] ✗ {title} (ingen träff)")

    # Spara cache
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    print(f"[TMDB] Klart: {len(posters)} affischer, {len(runtimes)} med längd "
          f"({hits} cachade, {misses} nya)")
    return posters, runtimes


def load_curtain_b64(static_dir: Path) -> str:
    """Läs ridåbilden och returnera som base64-sträng."""
    curtain_path = static_dir / "curtain.jpg"
    if curtain_path.exists():
        return base64.b64encode(curtain_path.read_bytes()).decode("ascii")
    return ""


def render_html(shows: list[Show], dates: list[str], output_path: Path,
                errors: list[str], posters: dict[str, str] | None = None,
                runtimes: dict[str, int] | None = None):
    base_dir = Path(__file__).parent
    env = Environment(
        loader=FileSystemLoader(str(base_dir / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tpl = env.get_template("index.html")

    static_dir = base_dir / "static"
    inline_css = (static_dir / "style.css").read_text(encoding="utf-8")
    inline_js = (static_dir / "app.js").read_text(encoding="utf-8")
    curtain_b64 = load_curtain_b64(static_dir)

    shows_sorted = sorted(shows, key=sort_key)
    generated_at = datetime.now(STOCKHOLM_TZ).strftime("%Y-%m-%d %H:%M")

    shows_json = json.dumps([asdict(s) for s in shows_sorted], ensure_ascii=False)
    dates_json = json.dumps(dates)
    errors_json = json.dumps(errors, ensure_ascii=False)
    posters_json = json.dumps(posters or {}, ensure_ascii=False)
    runtimes_json = json.dumps(runtimes or {}, ensure_ascii=False)

    html = tpl.render(
        page_title=f"På bio i Stockholm — {pretty_sv_date(dates[0])} till {pretty_sv_date(dates[-1])}",
        generated_at=generated_at,
        total_count=len(shows_sorted),
        source_count=len({s.source for s in shows_sorted if s.source}),
        shows_json=shows_json,
        dates_json=dates_json,
        errors_json=errors_json,
        posters_json=posters_json,
        runtimes_json=runtimes_json,
        inline_css=inline_css,
        inline_js=inline_js,
        curtain_b64=curtain_b64,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


# ── SCRAPER HISTORY (FALLBACK-CACHE) ────────────────────────────────
#
# Mål: om en scraper failar (eller returnerar 0 visningar trots att den
# brukar ha data) → använd förra körningens data så biografen inte
# försvinner från sajten helt.
#
# Format för output/scraper_history.json:
#   {
#     "Cinemateket Stockholm": {
#       "last_success": "2026-04-27",
#       "shows": [ {...}, {...} ]      # alla rader scrapern returnerade
#     },
#     ...
#   }
#
# Workflow:n committar tillbaka filen efter varje lyckad körning.

# Tröskel: hur många visningar krävs för att räkna "0 nu" som silent failure?
# Lugna veckor (Tellus, Reflexen) kan ha äkta noll-veckor. Detta kalibreras
# mot historisk data: om förra körningen hade < 3 visningar → vi vet inte
# om "tomt" är fel. Om den hade ≥ 3 → 0 nu = troligen scraper-fel.
SILENT_FAILURE_THRESHOLD = 3


def load_scraper_history(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_scraper_history(path: Path, history: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[VARNING] Kunde inte spara scraper-historik: {e}", file=sys.stderr)


def main():
    args = parse_args()
    dates = list(iter_dates(args.start_date, args.days))

    outdir = Path(__file__).parent / "output"
    index_out = outdir / "biosthlm.html"
    history_path = outdir / "scraper_history.json"
    history = load_scraper_history(history_path)

    sources = [
        ("Bio Fågel Blå", fetch_biofagelbla),
        ("Cinemateket Stockholm", fetch_cinemateket),
        ("Bio Rio", fetch_biorio),
        ("Bio Aspen", fetch_bioaspen),
        ("Capitol", fetch_capitol),
        ("Tellus", fetch_tellus),
        ("Zita", fetch_zita),
        ("Bio Skandia", fetch_bioskandia),
        ("Kulturhuset", fetch_kulturhuset),
        ("Bio Bristol", fetch_biobristol),
        ("Reflexen", fetch_reflexen),
    ]

    # Spåra per scraper: rader som hämtats och fel som uppstått
    session_rows: dict[str, list[dict]] = {label: [] for label, _ in sources}
    session_errors: dict[str, list[str]] = {label: [] for label, _ in sources}
    if args.include_filmstaden:
        session_rows["Filmstaden"] = []
        session_errors["Filmstaden"] = []

    # Hämta data per datum × scraper
    for d in dates:
        print(f"=== {d} ===")

        for label, fn in sources:
            try:
                rows = fn(target_date=d, timeout=args.timeout)
                session_rows[label].extend(rows)
                print(f"[OK] {label}: {len(rows)} visningar")
            except Exception as e:
                session_errors[label].append(f"{d}: {e}")
                print(f"[FEL] {label} {d}: {e}", file=sys.stderr)

        if args.include_filmstaden:
            try:
                rows = fetch_filmstaden_stockholm_stub(target_date=d, timeout=args.timeout)
                session_rows["Filmstaden"].extend(rows)
                print(f"[OK] Filmstaden Stockholm (stub): {len(rows)} visningar")
            except Exception as e:
                session_errors["Filmstaden"].append(f"{d}: {e}")
                print(f"[FEL] Filmstaden {d}: {e}", file=sys.stderr)

    # Konsolidera per scraper: använd ny data, fallback eller flagga som tomt
    today_iso = today_stockholm().isoformat()
    all_shows: list[Show] = []
    errors: list[str] = []

    for label in list(session_rows.keys()):
        rows = session_rows[label]
        errs = session_errors[label]
        prev = history.get(label, {})
        prev_shows = prev.get("shows", [])
        prev_date = prev.get("last_success", "")

        if rows:
            # Fick data — använd den och uppdatera historiken
            all_shows.extend(Show(**r) for r in rows)
            history[label] = {"last_success": today_iso, "shows": rows}

            if errs:
                # Partiellt fel: lyckades vissa dagar, failade andra
                errors.append(
                    f"{label}: nätverksfel för {len(errs)} av {len(dates)} dagar "
                    f"(senaste: {errs[-1]})"
                )
        else:
            # Inga rader. Tre fall: krasch, silent failure, eller äkta tomt.
            future_prev = [
                r for r in prev_shows if r.get("date", "") >= today_iso
            ]

            if errs:
                # Allt failade med exception
                if future_prev:
                    all_shows.extend(Show(**r) for r in future_prev)
                    errors.append(
                        f"{label}: alla {len(dates)} dagar failade — "
                        f"visar cachad data från {prev_date} "
                        f"({len(future_prev)} visningar)"
                    )
                    print(
                        f"[FALLBACK] {label}: {len(future_prev)} cachade visningar "
                        f"från {prev_date}"
                    )
                else:
                    errors.append(
                        f"{label}: alla {len(dates)} dagar failade "
                        f"({errs[-1]}) — ingen cachad data tillgänglig"
                    )
            elif len(prev_shows) >= SILENT_FAILURE_THRESHOLD:
                # Ingen krasch men 0 visningar trots att vi tidigare hade data
                # → troligen att sajten ändrat HTML eller att scrapern är trasig
                if future_prev:
                    all_shows.extend(Show(**r) for r in future_prev)
                    errors.append(
                        f"{label}: 0 visningar trots tidigare {len(prev_shows)} "
                        f"visningar — visar cachad data från {prev_date}"
                    )
                    print(
                        f"[TOMT] {label}: silent failure — använder fallback "
                        f"({len(future_prev)} visningar från {prev_date})",
                        file=sys.stderr,
                    )
                else:
                    errors.append(
                        f"{label}: 0 visningar och cachad data är för gammal"
                    )
                    print(
                        f"[TOMT] {label}: silent failure och cache är slut",
                        file=sys.stderr,
                    )
            else:
                # Aldrig haft mycket data — kan vara normalt (lugn vecka)
                print(f"[INFO] {label}: 0 visningar (ingen historik att jämföra med)")

    save_scraper_history(history_path, history)

    # Normalisera titlar: flytta format/språk/event till format_info
    normalize_shows(all_shows)

    # Städa format_info, ta bort dubblerade biografnamn, etc.
    clean_format_info(all_shows)

    # Hämta affischer och filmlängder från TMDB
    posters, runtimes = fetch_posters(all_shows)

    render_html(all_shows, dates, index_out, errors, posters=posters, runtimes=runtimes)
    print(f"Skapade HTML: {index_out}")

    if not args.no_history:
        hist = outdir / f"bio_stockholm_{dates[0]}_to_{dates[-1]}.html"
        hist.write_text(index_out.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Skapade historikfil: {hist}")

    cache = {
        "generated_at": datetime.now(STOCKHOLM_TZ).isoformat(),
        "dates": dates,
        "shows": [asdict(s) for s in sorted(all_shows, key=sort_key)],
        "errors": errors,
    }
    (outdir / "cache.json").write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Skapade cache: {outdir / 'cache.json'}")

    if errors:
        print("\nVarningar:")
        for e in errors:
            print(" -", e)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
