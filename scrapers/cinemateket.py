
from __future__ import annotations
import re
from bs4 import BeautifulSoup
from .common import abs_url, clean_spaces, get_html, parse_sv_date_text

URL = "https://www.filminstitutet.se/sv/se-och-samtala-om-film/cinemateket-stockholm/program/"

# In-memory cache: hela programsidan hämtas en gång per main.py-körning
# (även om fetch_cinemateket anropas en gång per dag i --days 5).
# Sidan filtreras lokalt på datum, så det räcker att hämta den en gång.
# main.py kör via cron och dör efter varje körning => inga stale data.
_html_cache: dict[str, str] = {}

def _parse_anchor(text: str, target_date: str):
    m = re.search(r'^(?P<title>.+?)\s+(?P<wd>mån|tis|ons|tor|fre|lör|sön)\s+(?P<dm>\d{1,2}/\d{1,2})\s+kl\.\s*(?P<time>\d{1,2}:\d{2})\s+(?P<rest>.+)$', text, flags=re.I)
    if not m: return None
    if parse_sv_date_text(m.group("dm"), default_year=int(target_date[:4])) != target_date: return None
    title = m.group("title").strip(" ,")
    rest = m.group("rest")
    venue = None
    for kv in ["Filmhuset - Bio Victor", "Filmhuset - Bio Mauritz", "Bio Skandia"]:
        if rest.startswith(kv): venue = kv; break
    fmt = None
    mf = re.search(r'\b(70\s*mm|35\s*mm)\b', title, flags=re.I)
    if mf: fmt = mf.group(1).replace(" ", "").lower().replace("mm", " mm")
    return {"title": title, "start_time": m.group("time"), "venue": venue, "format_info": fmt}

def fetch_cinemateket(target_date: str, timeout: int | tuple = (45, 30)):
    # Hämta en gång per process. Default-timeout är (45s connect, 30s read)
    # eftersom filminstitutet.se ofta har långsam initial TCP-handshake
    # från GitHub Actions-IP:er. get_html retry:ar automatiskt 3 gånger
    # vid timeout, så vid övergående nätverksstrul kommer vi igenom.
    if URL not in _html_cache:
        _html_cache[URL] = get_html(URL, timeout=timeout)
    html = _html_cache[URL]

    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        txt = clean_spaces(a.get_text(" ", strip=True))
        if " kl. " not in txt or not re.search(r"\b\d{1,2}/\d{1,2}\b", txt): continue
        p = _parse_anchor(txt, target_date)
        if not p: continue
        item = {"title":p["title"],"cinema":"Cinemateket Stockholm","start_time":p["start_time"],"date":target_date,"booking_url":abs_url(URL, a.get("href")),"format_info":p.get("format_info"),"district":"Östermalm","venue":p.get("venue"),"source":URL,"category":"film"}
        k = (item["title"], item["start_time"], item["venue"])
        if k in seen: continue
        seen.add(k); out.append(item)
    return sorted(out, key=lambda x:(x["start_time"], x["title"].lower()))
