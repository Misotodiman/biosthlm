# PROJEKT.md — På bio i Stockholm (biosthlm)

## Sammanfattning
Stockholms bio-aggregator. Python-backend scrapar ~15 biografer, normaliserar data, hämtar affischer/filmlängder från TMDB, och genererar en självförsörjande HTML-fil. Hostas gratis via GitHub Pages med daglig automatisk körning via GitHub Actions.

**Ägare:** Jonatan Etzler (GitHub: Misotodiman)
**Repo:** github.com/Misotodiman/biosthlm
**Live:** https://misotodiman.github.io/biosthlm/
**Cron:** 04:17 UTC dagligen (= 06:17 sommartid / 05:17 vintertid svensk tid)
**TMDB-token:** lagrad som GitHub secret `TMDB_API_TOKEN`

---

## Projektstruktur
```
~/bior/biorama v5/
├── main.py                  # Entry point: scrapar, normaliserar, TMDB, renderar HTML
├── templates/index.html     # Jinja2-mall för den slutgiltiga HTML-filen
├── static/
│   ├── style.css            # Mörkt tema, guld-accenter, responsiv design
│   ├── app.js               # Frontend: filter, filmlista, tidsslider, resultat
│   └── curtain.jpg          # Röd ridå-bakgrund för hero-sektionen
├── scrapers/
│   ├── common.py            # Delade hjälpfunktioner: get_html, clean_spaces, parse_hhmm, abs_url
│   ├── biofagelbla.py       # Bio Fågel Blå (Södermalm)
│   ├── biorio.py            # Bio Rio (Södermalm) — CSS-klasser: .kalender-day-group, .kalender-showtime-item
│   ├── bioaspen.py          # Bio Aspen (Aspudden) — hämtar venue (Salong 1 / Lusoperan) + specialvisningar
│   ├── bioskandia.py        # Bio Skandia (Norrmalm)
│   ├── biobristol.py        # Bio Bristol (Sundbyberg)
│   ├── capitol.py           # Capitol — titellänk = bokningslänk (/boka/{id}), sr-only spans för tid/salong
│   ├── cinemateket.py       # Cinemateket Stockholm (Filminstitutet) — timeout-känslig
│   ├── filmstaden.py        # Filmstaden — Playwright + cinema-api.com, alla biografer i Sverige
│   ├── kulturhuset.py       # Klarabiografen (Kulturhuset)
│   ├── reflexen.py          # Reflexen (Kärrtorp) — datumrubriker "12 april", bokningslänk med datum i URL
│   ├── tellus.py            # Tellus (Midsommarkransen) — h2-tider + h2-titellänkar, nortic.se-bokning
│   └── zita.py              # Zita (Birger Jarlsgatan)
├── .github/workflows/
│   └── build.yml            # GitHub Actions: daglig körning + deploy till Pages
└── output/
    ├── biosthlm.html        # Genererad sajt
    ├── cache.json            # Debug-cache med rå visningsdata
    └── poster_cache.json     # TMDB-affischer + filmlängder (format: {title: {poster_url, runtime}})
```

---

## main.py — Viktiga funktioner

### normalize_shows(shows)
Normaliserar titlar: strippar format/språk-suffix ("Operation bäver (sv tal)" → "Operation bäver"), 
dedupar fuzzy titelvarianter (Sirât/Sirāt, Tommy Tass), och korsrefererar mot råtitlar 
för att upptäcka okända format-tokens automatiskt.

### clean_format_info(shows)
Central rensning som körs EFTER normalisering. Hanterar ALL format_info-städning oavsett biograf:
- **Tar bort:** salongnamn (dubbletter), ljudformat (5.1, 7.1, Dolby), "Syntolkning via app", 
  "Familj", "Biopasset", "iSense", "XL", pris, datum, "Array", filmlängd-text, 
  "återkommande evenemang", "se alla one event"
- **Behåller:** IMAX, VIP-salong, 3D, 70mm, sv tal/eng tal, Barnvagnsbio, Frukostbio, 
  Seniorbio, Stickbio, Filmstudion, Knattebio, Påsklovsbio, regissörsbesök, 
  skådespelarbesök, Dine-in, Familjematiné, Afternoon Tea, premiär, förhandsvisning
- **Fixar dubblerade biografnamn:** "Bio Rio · Bio Rio" → "Bio Rio"
- **Rensar venue:** om venue == cinema → venue = None

### fetch_posters(shows)
TMDB-uppslag med multi-strategi fallback (sv-SE sen no-lang, strippar år/regissör-suffix, 
splittar på " - "). Returnerar (posters_dict, runtimes_dict). 
Cache i output/poster_cache.json med format {title: {"poster_url": ..., "runtime": int}}.

### render_html(shows, dates, output_path, posters, runtimes)
Renderar Jinja2-mallen. Serialiserar SHOWS, POSTERS, RUNTIMES, DATES, ERRORS som JSON 
i HTML-filen så frontenden kan använda dem direkt.

---

## Frontend (app.js + style.css)

### Design
- Mörkt tema: #0e0c0b bakgrund, guld-accenter (#c9a84c), cream-text (#f5ead0)
- Hero med röd ridå-bakgrundsbild + "På bio i Stockholm" i serif
- Responsiv: breakpoints vid 520px och 600px

### Biografgrupper
- **INNERSTAD:** Bio Fågel Blå, Bio Rio, Bio Skandia, Capitol, Cinemateket Stockholm, 
  Filmstaden Rigoletto, Filmstaden Sergel, Grand Stockholm, Klarabiografen, Saga, 
  Sture, Victoria Stockholm, Zita
- **CINEVILLE:** Bio Aspen, Bio Bristol, Tellus, Reflexen, Bio Skandia, Klarabiografen, 
  Skärisbiografen, Zita (OBS: Folkets Hus Kallhäll är INTE med — ingen scraper)

### Paneler och filter
- **Biografer-panel** (kollapsbar, stängd default): Innerstad · Cineville · Alla · Rensa-knappar, 
  sen grid med alla biografer
- **Filmer-panel** (kollapsbar, stängd default): sökfält, Alla/Rensa, scrollbar grid med 
  filmkort (TMDB-poster 30×44px, runtime, antal visningar)
- **Filmlistan är dynamisk:** filtreras av dag + tid + biograf — visar bara filmer som 
  har matchande visningar. Om valda filmer försvinner pga ändrade filter rensas de automatiskt.
- **Dagstrip:** multi-select pills (default alla valda)
- **Tidsslider:** dual-range 06:00–24:00 (Kayak-stil)
- **localStorage:** nyckel `bio-sthlm-fav-cinemas` sparar favoritbiografer

### Visningskort (3-radsdesign för mobil)
- Rad 1: Titel + format-taggar (guld)
- Rad 2: Biograf · Salong (ljusgrå, --text-muted)
- Rad 3: "120 min · klar ca 15:25" (mörkgrå, --text-dim) — runtime från TMDB + 10 min reklambuffer
- Boka-knapp till höger (länk till biografens bokningssida)

### Footer
TMDB-attribution med SVG-logga + disclaimer-text.

---

## Scrapers — Viktiga detaljer

### Bio Rio (biorio.py)
Next.js-sajt. Struktur: `.kalender-day-group` → `<h2>` med datum ("Idag 7 april") → 
`.kalender-showtime-item` med tid, titel, salong, längd. Länktexten i `<a>` är TOM — 
all info ligger i föräldra-div:en. Bokningslänk: `/sv/boka/{id}`.

### Capitol (capitol.py)
Next.js-sajt (ombyggd ~april 2026). Titellänken (`<a href="/boka/{id}">`) ÄR 
bokningslänken. Tid ligger i `<span class="sr-only">(17:20)</span>`. Salong ligger i 
badge-spans: `<span class="sr-only">Salong </span><span>4</span>`. 
Format (Dine-in, Frukostbio etc) i div-syskon direkt efter titellänken.
OBS: get_text() på titellänken ger skräp ("Josef Mengeles försvinnande 4, 17:20") 
om man inte hoppar över span-barn.

### Filmstaden (filmstaden.py)
Använder Playwright för att hämta data via cinema-api.com (kräver browser-session från 
mobile.filmstaden.se). Hämtar ALLA Filmstaden-biografer i Sverige, filtreras i main.py.
Bokningslänk: `https://www.filmstaden.se/film/{slug}/` (hämtas från movie-API:ets slug-fält).
Workflow installerar Playwright: `pip install playwright && python -m playwright install chromium && python -m playwright install-deps chromium`.

### Tellus (tellus.py)
Dag-vy med `<h2>`-taggar: tid-h2 (bara "19:30") följt av titel-h2 (med länk till event-sida).
Bokningslänk scrapas från event-sidan ("Köp biljett"-länk till nortic.se).
Använder common.get_html (inte egen requests.get) för att undvika 415-fel på GitHub.

### Bio Aspen (bioaspen.py)
Paginerad listvy. Datumrubriker ("onsdag, 25 februari") följda av visningslänkar.
Varje länks text innehåller: tid, titel, längd, åldersgräns, ljud, språk, salong.
Scrapern plockar ut venue (Salong 1 / Lusoperan) och specialvisningar 
("- Seniorbio", "- Barnvagnsbio") ur titeln → format_info.

### Reflexen (reflexen.py)
Datumrubriker "12 april" → "kl HH:MM"-länk + titel-länk som syskon.
Bokningslänkar har datum i URL (/20260412/1300/) — används som dubbelcheck.
"Filmstudion: Drömmar" → titel "Drömmar", format "Filmstudion".

### Cinemateket (cinemateket.py)
Scrapar filminstitutet.se. Timeout-känslig — sajten svarar inte alltid från GitHub:s servrar.

---

## GitHub Actions (build.yml)
```yaml
Cron: '17 4 * * *'  # 04:17 UTC
Python 3.12
Beroenden: requests, beautifulsoup4, jinja2, playwright
Playwright: chromium installeras vid varje körning
TMDB_API_TOKEN: från GitHub secrets
Kommando: python main.py --days 5 --include-filmstaden --no-history
Deploy: GitHub Pages via actions/deploy-pages@v4
```

---

## Kända problem och beslut
- **Cinemateket:** timeout-fel från GitHub:s servrar ibland. Fungerar oftast dagen efter.
- **Filmstaden API:** kräver Playwright-session. Kan inte hämtas med vanliga requests (403).
- **TMDB:** gratis API för icke-kommersiellt bruk. Ej godkänt för kommersiell användning utan avtal.
- **Cache:** radera output/poster_cache.json om TMDB-resultat verkar stale.
- **GitHub Actions-schema:** nya/ändrade cron-scheman kan ta upp till 24h att börja triggas.
  Udda minuter (t.ex. :17) är mer pålitliga än :00.
- **Node.js 20-varningar:** GitHub varnar att actions ska uppgraderas till Node.js 24 
  före juni 2026. Inte akut.

---

## Framtida planer
- GitHub Issues-notiser vid scraper-fel
- Expandera till hela Sverige (GBG, Malmö — Filmstaden täcker redan alla städer)
- PWA-stöd (manifest.json + service worker) för "installera på hemskärmen"
- Köpa domän (t.ex. pabio.se)
- Eventuellt: konserter, teater, dans som extra kategorier
- Eventuellt: platstjänster (Geolocation API) för "biografer nära mig"

---

## Jonatans preferenser
- Kommunicerar på svenska
- Använder mobil primärt
- Färgblind — undvik att förlita sig enbart på färgskillnader
- Föredrar pragmatisk enkelhet, minimalt fram-och-tillbaka
- Inte programmerare — behöver tydliga terminalkommandon steg för steg
- macOS, projektmapp: ~/bior/biorama v5/
- GitHub-användarnamn: Misotodiman (stort M)
- Personal Access Token: sparad i macOS Keychain, 90 dagars giltighetstid (skapad ~12 april 2026)
