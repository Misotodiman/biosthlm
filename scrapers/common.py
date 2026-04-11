
from __future__ import annotations
import re
from datetime import date, datetime
from urllib.parse import urljoin
import requests

def get_html(url: str, timeout: int = 20) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    r = requests.get(url, timeout=timeout, headers=headers)
    r.raise_for_status()
    return r.text

def abs_url(base_url: str, href: str | None) -> str | None:
    return urljoin(base_url, href) if href else None

def clean_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def parse_hhmm(text: str) -> str | None:
    m = re.search(r"(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)", text or "")
    return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}" if m else None

SV_MONTHS = {"jan":1,"januari":1,"feb":2,"februari":2,"mar":3,"mars":3,"apr":4,"april":4,"maj":5,"jun":6,"juni":6,"jul":7,"juli":7,"aug":8,"augusti":8,"sep":9,"sept":9,"september":9,"okt":10,"oktober":10,"nov":11,"november":11,"dec":12,"december":12}

def parse_sv_date_text(text: str, default_year: int | None = None) -> str | None:
    s = (text or "").lower()
    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?", s)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        yraw = m.group(3)
        if yraw:
            y = int(yraw)
            if y < 100: y += 2000
        else:
            y = default_year or datetime.now().year
        return date(y, mo, d).isoformat()
    m = re.search(r"(\d{1,2})\s+([a-zåäö]+)", s)
    if m:
        d, mon = int(m.group(1)), m.group(2)
        mo = SV_MONTHS.get(mon)
        if mo:
            return date(default_year or datetime.now().year, mo, d).isoformat()
    return None
