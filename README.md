# Bio-schema Stockholm v2

## Kör
```bash
cd ~/Downloads/bio-schema-stockholm-v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --days 5
```

Med Filmstaden-stub (hämtar sida men inga showtimes ännu):
```bash
python main.py --days 5 --include-filmstaden
```

Ladda upp:
- `output/index.html` till Cargo (samma URL varje dag)


## Filmstaden (403)
Filmstaden kan blockera vanliga requests. Den här versionen försöker först requests och faller sedan tillbaka till Playwright.

Efter `pip install -r requirements.txt`, kör även:

```bash
python -m playwright install chromium
```
