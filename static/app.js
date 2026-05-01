(function () {
  "use strict";

  // ── INNERSTAD ──
  var INNERSTAD = new Set([
    "Bio Fågel Blå", "Bio Rio", "Bio Skandia", "Capitol",
    "Cinemateket Stockholm", "Filmstaden Rigoletto", "Filmstaden Sergel",
    "Grand Stockholm", "Klarabiografen", "Saga", "Sture",
    "Victoria Stockholm", "Zita"
  ]);

  // ── CINEVILLE ──
  var CINEVILLE = new Set([
    "Bio Aspen", "Bio Bristol", "Tellus", "Reflexen", "Bio Skandia",
    "Folkets Hus Kallhäll", "Klarabiografen", "Skärisbiografen", "Zita"
  ]);

  // ── SWEDISH LABELS ──
  var SV_DAYS = ["Sön", "Mån", "Tis", "Ons", "Tor", "Fre", "Lör"];
  var SV_DAYS_LONG = ["Söndag", "Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag"];
  var SV_MONTHS = [
    "januari", "februari", "mars", "april", "maj", "juni",
    "juli", "augusti", "september", "oktober", "november", "december"
  ];

  function prettyDate(iso) {
    var d = new Date(iso + "T12:00:00");
    return SV_DAYS_LONG[d.getDay()] + " " + d.getDate() + " " + SV_MONTHS[d.getMonth()];
  }
  function shortDate(iso) {
    var d = new Date(iso + "T12:00:00");
    return SV_DAYS[d.getDay()] + " " + d.getDate();
  }

  // ── STATE ──
  var selectedCinemas = new Set();
  var selectedFilms = new Set();
  // selectedDays initieras i init() efter visibleDates() är definierad
  var selectedDays = new Set();
  var timeMin = 360;   // 06:00
  var timeMax = 1440;  // 24:00

  // Restore cinema favorites
  try {
    var saved = JSON.parse(localStorage.getItem("bio-sthlm-fav-cinemas") || "[]");
    if (saved.length) selectedCinemas = new Set(saved);
  } catch (e) {}

  function timeToMin(t) {
    var parts = t.split(":");
    return parseInt(parts[0], 10) * 60 + parseInt(parts[1] || "0", 10);
  }

  function minToTime(m) {
    var h = Math.floor(m / 60);
    var mm = m % 60;
    return (h < 10 ? "0" : "") + h + ":" + (mm < 10 ? "0" : "") + mm;
  }

  function todayIso() {
    var d = new Date();
    return d.getFullYear() + "-" +
      String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0");
  }

  // Returnerar de datum från DATES som ska visas:
  // - Backend hämtar 6 dagar som buffert (eftersom Actions kör nyckfullt sent)
  // - Vi visar max 5 dagar för att hålla layouten konsekvent
  // - Vi slänger "idag" om alla visningar redan passerat (= fredag kl 23:00
  //   ska inte visa "Fre 0" eftersom alla visningar redan har börjat)
  // - Vid midnatt triggas en omrendering så gårdagens dag försvinner och
  //   en framtida dag dyker upp ur bufferten
  function visibleDates() {
    var today = todayIso();
    var now = nowMinutes();

    var future = DATES.filter(function (d) {
      if (d < today) return false;
      if (d > today) return true;
      // d === today: visa bara om det finns minst en visning kvar idag
      return SHOWS.some(function (s) {
        return s.date === today && timeToMin(s.start_time) >= now;
      });
    });

    // Cappa till max 5 dagar — bufferten ska inte synas förrän vi behöver den
    return future.slice(0, 5);
  }

  function nowMinutes() {
    var d = new Date();
    return d.getHours() * 60 + d.getMinutes();
  }

  function escHtml(s) {
    var el = document.createElement("span");
    el.textContent = s;
    return el.innerHTML;
  }

  function saveCinemas() {
    try { localStorage.setItem("bio-sthlm-fav-cinemas", JSON.stringify(Array.from(selectedCinemas))); } catch (e) {}
  }

  // ── FILTERING ──
  function filteredShows() {
    var today = todayIso();
    var now = nowMinutes();
    var hasCinemaFilter = selectedCinemas.size > 0;
    var hasFilmFilter = selectedFilms.size > 0;

    return SHOWS.filter(function (s) {
      // Day filter
      if (!selectedDays.has(s.date)) return false;
      // Hide past shows for today
      if (s.date === today && timeToMin(s.start_time) < now) return false;
      // Time range
      var m = timeToMin(s.start_time);
      if (m < timeMin || m > timeMax) return false;
      // Cinema filter (if any selected)
      if (hasCinemaFilter && !selectedCinemas.has(s.cinema)) return false;
      // Film filter (if any selected)
      if (hasFilmFilter && !selectedFilms.has(s.title)) return false;
      return true;
    }).sort(function (a, b) {
      if (a.date !== b.date) return a.date.localeCompare(b.date);
      return a.start_time.localeCompare(b.start_time);
    });
  }

  // ── COLLAPSIBLE PANELS ──
  function setupPanel(toggleId, panelId) {
    var toggle = document.getElementById(toggleId);
    var panel = document.getElementById(panelId);
    toggle.addEventListener("click", function () {
      panel.classList.toggle("open");
    });
  }

  // ── ERRORS ──
  function renderErrors() {
    if (!ERRORS || !ERRORS.length) return;
    document.getElementById("errors-container").innerHTML =
      '<section class="notice"><details><summary>Varningar (' + ERRORS.length +
      ")</summary><ul>" + ERRORS.map(function (e) { return "<li>" + escHtml(e) + "</li>"; }).join("") +
      "</ul></details></section>";
  }

  // ── CINEMAS ──
  function getAllCinemas() {
    return Array.from(new Set(SHOWS.map(function (s) { return s.cinema; })))
      .sort(function (a, b) { return a.localeCompare(b, "sv"); });
  }

  function renderCinemas() {
    var allCinemas = getAllCinemas();
    var inner = allCinemas.filter(function (c) { return INNERSTAD.has(c); });
    var cineville = allCinemas.filter(function (c) { return CINEVILLE.has(c); });
    var outer = allCinemas.filter(function (c) { return !INNERSTAD.has(c); });
    var ordered = inner.concat(outer);

    // Quick actions
    var qa = document.getElementById("cinema-quick");
    qa.innerHTML =
      '<button class="quick-btn" id="btn-c-inner">Innerstad</button>' +
      '<button class="quick-btn" id="btn-c-cineville">Cineville</button>' +
      '<button class="quick-btn" id="btn-c-all">Alla</button>' +
      '<button class="quick-btn" id="btn-c-none">Rensa</button>';

    document.getElementById("btn-c-inner").addEventListener("click", function () {
      selectedCinemas = new Set(inner); saveCinemas(); renderCinemas(); renderFilms(); renderResults();
    });
    document.getElementById("btn-c-cineville").addEventListener("click", function () {
      selectedCinemas = new Set(cineville); saveCinemas(); renderCinemas(); renderFilms(); renderResults();
    });
    document.getElementById("btn-c-all").addEventListener("click", function () {
      selectedCinemas = new Set(allCinemas); saveCinemas(); renderCinemas(); renderFilms(); renderResults();
    });
    document.getElementById("btn-c-none").addEventListener("click", function () {
      selectedCinemas.clear(); saveCinemas(); renderCinemas(); renderFilms(); renderResults();
    });

    // Grid
    var grid = document.getElementById("cinema-grid");
    grid.innerHTML = ordered.map(function (c) {
      return '<div class="cinema-chip' + (selectedCinemas.has(c) ? " active" : "") +
        '" data-cinema="' + escHtml(c) + '"><span class="cinema-dot"></span>' + escHtml(c) + "</div>";
    }).join("");

    grid.querySelectorAll(".cinema-chip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var c = chip.dataset.cinema;
        if (selectedCinemas.has(c)) selectedCinemas.delete(c);
        else selectedCinemas.add(c);
        saveCinemas(); renderCinemas(); renderFilms(); renderResults();
      });
    });

    // Meta
    document.getElementById("cinema-meta").textContent =
      selectedCinemas.size ? selectedCinemas.size + " valda" : "alla";
  }

  // ── FILMS ──
  function renderFilms() {
    var search = (document.getElementById("film-search").value || "").toLowerCase();
    var today = todayIso();
    var now = nowMinutes();
    var hasCinemaFilter = selectedCinemas.size > 0;

    // Collect unique films that match current day + time + cinema filters
    var films = {};
    var daysToCheck = selectedDays.size ? selectedDays : new Set(visibleDates());
    SHOWS.forEach(function (s) {
      if (!daysToCheck.has(s.date)) return;
      // Hide past shows for today
      if (s.date === today && timeToMin(s.start_time) < now) return;
      // Time range
      var m = timeToMin(s.start_time);
      if (m < timeMin || m > timeMax) return;
      // Cinema filter
      if (hasCinemaFilter && !selectedCinemas.has(s.cinema)) return;

      if (!films[s.title]) films[s.title] = { title: s.title, count: 0 };
      films[s.title].count++;
    });

    var sorted = Object.values(films).sort(function (a, b) {
      return a.title.localeCompare(b.title, "sv");
    });

    // Rensa bort valda filmer som inte längre matchar filtren
    if (selectedFilms.size) {
      var available = new Set(sorted.map(function (f) { return f.title; }));
      selectedFilms.forEach(function (f) {
        if (!available.has(f)) selectedFilms.delete(f);
      });
    }

    if (search) {
      sorted = sorted.filter(function (f) {
        return f.title.toLowerCase().indexOf(search) !== -1;
      });
    }

    // Quick actions
    var qa = document.getElementById("film-quick");
    qa.innerHTML =
      '<button class="quick-btn" id="btn-f-all">Alla</button>' +
      '<button class="quick-btn" id="btn-f-none">Rensa</button>';

    document.getElementById("btn-f-all").addEventListener("click", function () {
      selectedFilms = new Set(sorted.map(function (f) { return f.title; }));
      renderFilms(); renderResults();
    });
    document.getElementById("btn-f-none").addEventListener("click", function () {
      selectedFilms.clear(); renderFilms(); renderResults();
    });

    // Grid
    var grid = document.getElementById("film-grid");
    if (!sorted.length) {
      grid.innerHTML = '<div class="empty-state">Inga filmer matchar</div>';
    } else {
      grid.innerHTML = sorted.map(function (f) {
        var posterUrl = POSTERS[f.title];
        var posterHtml = posterUrl
          ? '<img class="film-card-poster" src="' + escHtml(posterUrl) + '" alt="" loading="lazy">'
          : '<div class="film-card-poster-placeholder">&#127910;</div>';
        var runtime = RUNTIMES[f.title];
        var rtHtml = runtime ? '<div class="film-card-runtime">' + runtime + ' min</div>' : "";
        return (
          '<div class="film-card' + (selectedFilms.has(f.title) ? " selected" : "") +
          '" data-film="' + escHtml(f.title) + '">' +
          posterHtml +
          '<div class="film-card-body">' +
          '<div class="film-card-title">' + escHtml(f.title) + "</div>" +
          rtHtml +
          "</div>" +
          '<div class="film-card-count">' + f.count + " visn.</div>" +
          "</div>"
        );
      }).join("");
    }

    grid.querySelectorAll(".film-card").forEach(function (card) {
      card.addEventListener("click", function () {
        var film = card.dataset.film;
        if (selectedFilms.has(film)) selectedFilms.delete(film);
        else selectedFilms.add(film);
        renderFilms(); renderResults();
      });
    });

    // Meta
    document.getElementById("film-meta").textContent =
      selectedFilms.size ? selectedFilms.size + " valda" : "alla";
  }

  // ── DAYS ──
  function renderDays() {
    var strip = document.getElementById("day-strip");
    var today = todayIso();
    var now = nowMinutes();
    strip.innerHTML = visibleDates().map(function (d) {
      var count = SHOWS.filter(function (s) {
        if (s.date !== d) return false;
        if (d === today && timeToMin(s.start_time) < now) return false;
        return true;
      }).length;
      return '<button class="day-pill' + (selectedDays.has(d) ? " active" : "") +
        '" data-day="' + d + '">' + shortDate(d) +
        '<span class="day-pill-count">' + count + "</span></button>";
    }).join("");

    strip.querySelectorAll(".day-pill").forEach(function (pill) {
      pill.addEventListener("click", function () {
        var day = pill.dataset.day;
        if (selectedDays.has(day)) {
          selectedDays.delete(day);
          // Don't allow zero days — reselect if last was removed
          if (selectedDays.size === 0) selectedDays = new Set(visibleDates());
        } else {
          selectedDays.add(day);
        }
        renderDays(); renderFilms(); renderResults();
      });
    });
  }

  // ── TIME SLIDER ──
  function setupTimeSlider() {
    var elMin = document.getElementById("time-min");
    var elMax = document.getElementById("time-max");
    var fill = document.getElementById("range-fill");
    var label = document.getElementById("time-label");

    function updateFill() {
      var lo = parseInt(elMin.value, 10);
      var hi = parseInt(elMax.value, 10);
      var range = parseInt(elMin.max, 10) - parseInt(elMin.min, 10);
      var minPct = ((lo - parseInt(elMin.min, 10)) / range) * 100;
      var maxPct = ((hi - parseInt(elMin.min, 10)) / range) * 100;
      fill.style.left = minPct + "%";
      fill.style.width = (maxPct - minPct) + "%";
      label.textContent = minToTime(lo) + " – " + minToTime(hi);
    }

    function onChange() {
      var lo = parseInt(elMin.value, 10);
      var hi = parseInt(elMax.value, 10);
      if (lo > hi) { elMin.value = hi; lo = hi; }
      timeMin = lo;
      timeMax = hi;
      updateFill();
      renderFilms();
      renderResults();
    }

    elMin.addEventListener("input", function () {
      if (parseInt(elMin.value, 10) > parseInt(elMax.value, 10)) {
        elMin.value = elMax.value;
      }
      onChange();
    });
    elMax.addEventListener("input", function () {
      if (parseInt(elMax.value, 10) < parseInt(elMin.value, 10)) {
        elMax.value = elMin.value;
      }
      onChange();
    });

    updateFill();
  }

  // ── RESULTS ──
  function renderShowItem(s) {
    var fmt = s.format_info ? '<span class="show-format">' + escHtml(s.format_info) + "</span>" : "";

    // Filmlängd + beräknad sluttid (start + längd + 10 min reklam)
    var runtime = RUNTIMES[s.title];
    var runtimeHtml = "";
    if (runtime) {
      var startMin = timeToMin(s.start_time);
      var endMin = (startMin + runtime + 10) % 1440;
      var endTime = minToTime(endMin);
      runtimeHtml = '<div class="show-runtime">' + runtime + ' min · klar ca ' + endTime + '</div>';
    }

    var link = s.booking_url
      ? '<a href="' + escHtml(s.booking_url) + '" class="show-link" target="_blank" rel="noopener">Boka</a>'
      : "";
    var venueHtml = s.venue ? " \u00b7 " + escHtml(s.venue) : "";
    return (
      '<div class="show-item">' +
      '<span class="show-time">' + escHtml(s.start_time) + "</span>" +
      '<div class="show-info">' +
      '<div class="show-title">' + escHtml(s.title) + fmt + "</div>" +
      '<div class="show-venue">' + escHtml(s.cinema) + venueHtml + "</div>" +
      runtimeHtml +
      "</div>" + link + "</div>"
    );
  }

  function renderResults() {
    var shows = filteredShows();
    var titleEl = document.getElementById("results-title");
    var countEl = document.getElementById("results-count");
    var listEl = document.getElementById("results-list");

    titleEl.textContent = "Visningar";
    countEl.textContent = shows.length + " visningar";

    if (!shows.length) {
      listEl.innerHTML = '<div class="empty-state">Inga visningar matchar filtren</div>';
      return;
    }

    // Group by day
    var byDay = {};
    shows.forEach(function (s) {
      if (!byDay[s.date]) byDay[s.date] = [];
      byDay[s.date].push(s);
    });

    var html = "";
    Object.keys(byDay).sort().forEach(function (day) {
      html += '<div class="day-section">' +
        '<div class="day-section-title">' + prettyDate(day) + " \u00b7 " + byDay[day].length + " visningar</div>" +
        '<div class="show-list">' + byDay[day].map(renderShowItem).join("") + "</div></div>";
    });
    listEl.innerHTML = html;
  }

  // ── FILM SEARCH ──
  document.getElementById("film-search").addEventListener("input", renderFilms);

  // ── MIDNATTS-TIMER ──
  // Vid midnatt: rensa bort gårdagens dag från selectedDays och rendera om allt.
  // Det gör att om någon har sajten öppen i bakgrunden över en dag, så
  // försvinner gårdagens dag-pill automatiskt utan att de behöver ladda om.
  function scheduleMidnightRefresh() {
    var now = new Date();
    var nextMidnight = new Date(
      now.getFullYear(), now.getMonth(), now.getDate() + 1,
      0, 0, 5  // 5 sekunder efter midnatt för att undvika race med datum-rollover
    );
    var msUntilMidnight = nextMidnight.getTime() - now.getTime();

    setTimeout(function () {
      // Rensa bort dagar som inte längre är synliga (gårdagens datum osv)
      var visible = new Set(visibleDates());
      selectedDays.forEach(function (d) {
        if (!visible.has(d)) selectedDays.delete(d);
      });
      // Om allt rensats bort, välj alla synliga som default
      if (selectedDays.size === 0) selectedDays = new Set(visibleDates());

      // Rendera om allt så dagstrip + visningar uppdateras
      renderDays();
      renderFilms();
      renderResults();

      // Schemalägg nästa midnatt
      scheduleMidnightRefresh();
    }, msUntilMidnight);
  }

  // ── INIT ──
  // Initiera selectedDays till alla synliga dagar (idag + framåt)
  selectedDays = new Set(visibleDates());

  setupPanel("toggle-cinemas", "panel-cinemas");
  setupPanel("toggle-films", "panel-films");

  renderErrors();
  renderCinemas();
  renderFilms();
  renderDays();
  setupTimeSlider();
  renderResults();
  scheduleMidnightRefresh();
})();
