
from __future__ import annotations
import re
from bs4 import BeautifulSoup
from .common import abs_url, clean_spaces, get_html
URL = "https://biofagelbla.se/program/"
MONTHS = {1:"januari",2:"februari",3:"mars",4:"april",5:"maj",6:"juni",7:"juli",8:"augusti",9:"september",10:"oktober",11:"november",12:"december"}
def _looks_like_date_header(t: str) -> bool:
    t = (t or "").lower()
    return any(d in t for d in ["måndag","tisdag","onsdag","torsdag","fredag","lördag","söndag"])
def _header_matches_target(text: str, target_date: str) -> bool:
    _, mm, dd = target_date.split("-")
    return str(int(dd)) in (text or "").lower() and MONTHS[int(mm)] in (text or "").lower()
def _parse_show_header(text: str):
    m = re.match(r'^\s*[“"]?(.*?)[”"]?\s+(\d{1,2}:\d{2})\s*$', text or "")
    return ((clean_spaces(m.group(1)).strip('“”" '), m.group(2)) if m else (None, None))
def _regex_fallback(html: str, target_date: str):
    _,m,d = map(int, target_date.split("-"))
    month_map = {1:"Januari",2:"Februari",3:"Mars",4:"April",5:"Maj",6:"Juni",7:"Juli",8:"Augusti",9:"September",10:"Oktober",11:"November",12:"December"}
    sec = re.search(rf"###\s+.*?{d}(?:st|nd|rd|th)\s+{month_map[m]}(.*?)(?:###\s+[A-ZÅÄÖa-zåäö]+,\s+\d+(?:st|nd|rd|th)\s+|$)", html, flags=re.S)
    if not sec: return []
    out=[]
    for mm in re.finditer(r"###\s+[“\"]?(.*?)[”\"]?\s+(\d{1,2}:\d{2})", sec.group(1)):
        out.append({"title":clean_spaces(mm.group(1)).strip('“”" '),"cinema":"Bio Fågel Blå","start_time":mm.group(2),"date":target_date,"booking_url":None,"format_info":None,"district":"Södermalm","venue":"Bio Fågel Blå","source":URL,"category":"film"})
    return out
def fetch_biofagelbla(target_date: str, timeout: int = 20):
    html = get_html(URL, timeout=timeout)
    soup = BeautifulSoup(html, "html.parser")
    target = None
    for h in soup.find_all(["h2","h3","h4"]):
        if _header_matches_target(clean_spaces(h.get_text(" ", strip=True)), target_date):
            target = h; break
    if target is None: return _regex_fallback(html, target_date)
    out=[]; node = target
    while True:
        node = node.find_next()
        if node is None: break
        if getattr(node,"name",None) in {"h2","h3","h4"}:
            txt = clean_spaces(node.get_text(" ", strip=True))
            if _looks_like_date_header(txt): break
            title, hhmm = _parse_show_header(txt)
            if title and hhmm:
                booking_url = None
                scan = node
                for _ in range(12):
                    scan = scan.find_next()
                    if scan is None: break
                    if getattr(scan,"name",None) == "a" and "biljetter" in clean_spaces(scan.get_text(" ", strip=True)).lower():
                        booking_url = abs_url(URL, scan.get("href")); break
                    if getattr(scan,"name",None) in {"h2","h3","h4"}: break
                out.append({"title":title,"cinema":"Bio Fågel Blå","start_time":hhmm,"date":target_date,"booking_url":booking_url,"format_info":None,"district":"Södermalm","venue":"Bio Fågel Blå","source":URL,"category":"film"})
    return out
