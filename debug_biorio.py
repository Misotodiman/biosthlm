"""Kör: python3 debug_biorio.py
Hjälper oss se vad scrapern faktiskt ser."""
import sys
from pathlib import Path

# Lägg till projektmappen så vi kan importera scrapers.common
sys.path.insert(0, str(Path(__file__).parent))

from bs4 import BeautifulSoup
from scrapers.common import get_html, clean_spaces

URL = "https://www.biorio.se/sv/kalender"

html = get_html(URL, timeout=20)
print(f"HTML längd: {len(html)} tecken\n")

soup = BeautifulSoup(html, "html.parser")

# 1. Hitta alla h2/h3
print("=" * 60)
print("RUBRIKER (h1, h2, h3):")
print("=" * 60)
for h in soup.find_all(["h1", "h2", "h3"]):
    text = clean_spaces(h.get_text(" ", strip=True))
    print(f"  <{h.name}> {text!r}")

# 2. Hitta alla länkar med /boka/
print("\n" + "=" * 60)
print("BOKNINGSLÄNKAR (första 10):")
print("=" * 60)
boka_links = soup.find_all("a", href=lambda h: h and "/boka/" in h)
print(f"Totalt: {len(boka_links)} länkar\n")
for link in boka_links[:10]:
    text = clean_spaces(link.get_text(" ", strip=True))
    href = link.get("href", "")
    print(f"  href={href}")
    print(f"  text={text!r}")
    parent = link.parent
    if parent:
        ptext = clean_spaces(parent.get_text(" ", strip=True))
        print(f"  parent.name={parent.name}, parent.text={ptext[:120]!r}")
    print()

# 3. Hur ligger länkarna i förhållande till rubrikerna?
print("=" * 60)
print("STRUKTUR-CHECK: vad är gemensam förälder?")
print("=" * 60)
if boka_links:
    first_link = boka_links[0]
    p = first_link
    for i in range(8):
        p = p.parent
        if p is None:
            break
        print(f"  förälder {i+1}: <{p.name}> "
              f"klass={p.get('class')} id={p.get('id')}")
