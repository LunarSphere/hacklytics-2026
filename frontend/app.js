/* ==========================================================
   Fraud Risk Analysis — Vanilla JS
   ========================================================== */

(function () {
  "use strict";

  /* ----------------------------------------------------------
     DOM references
     ---------------------------------------------------------- */
  var tickerInput   = document.getElementById("ticker-input");
  var tickerCount   = document.getElementById("ticker-count");
  var tickerChips   = document.getElementById("ticker-chips");
  var analyzeBtn    = document.getElementById("analyze-btn");
  var btnLabel      = document.getElementById("btn-label");
  var progressFill  = document.getElementById("progress-fill");
  var shortcutHint  = document.getElementById("shortcut-hint");
  var skeletonSec   = document.getElementById("skeleton-section");
  var resultsSec    = document.getElementById("results-section");
  var stockCardsContainer = document.getElementById("stock-cards-container");
  var downloadBtn   = document.getElementById("download-btn");
  var downloadLabel = document.getElementById("download-label");
  var reportSummary     = document.getElementById("report-summary");
  var reportSummaryText = document.getElementById("report-summary-text");

  // Carousel
  var carouselNav     = document.getElementById("carousel-nav");
  var carouselPrev    = document.getElementById("carousel-prev");
  var carouselNext    = document.getElementById("carousel-next");
  var carouselCounter = document.getElementById("carousel-counter");
  var carouselDots    = document.getElementById("carousel-dots");
  var carouselHint    = document.getElementById("carousel-hint");

  // Auth
  var authBar         = document.getElementById("auth-bar");
  var authLink        = document.getElementById("auth-link");
  var authModal       = document.getElementById("auth-modal");
  var modalBackdrop   = document.getElementById("modal-backdrop");
  var modalTitle      = document.getElementById("modal-title");
  var modalDesc       = document.getElementById("modal-desc");
  var nameField       = document.getElementById("name-field");
  var authNameInput   = document.getElementById("auth-name");
  var authPhoneInput  = document.getElementById("auth-phone");
  var phoneFormatHint = document.getElementById("phone-format-hint");
  var phoneDigitCount = document.getElementById("phone-digit-count");
  var modalSubmit     = document.getElementById("modal-submit");
  var modalToggle     = document.getElementById("modal-toggle");
  var modalTogglePrompt = document.getElementById("modal-toggle-prompt");

  // Portfolio
  var portfolioBtn       = document.getElementById("portfolio-btn");
  var portfolioHint      = document.getElementById("portfolio-hint");
  var portfolioIndicator = document.getElementById("portfolio-indicator");
  var portfolioLabel     = document.getElementById("portfolio-label");
  var portfolioChips     = document.getElementById("portfolio-chips");

  /* ----------------------------------------------------------
     Severity color map
     ---------------------------------------------------------- */
  function getScoreColor(score) {
    if (score <= 25) return "#3a8a5c";
    if (score <= 50) return "#8a8a3a";
    if (score <= 75) return "#c49a3a";
    return "#b83a2a";
  }

  function getScoreLabel(score) {
    if (score <= 25) return "LOW";
    if (score <= 50) return "MODERATE";
    if (score <= 75) return "ELEVATED";
    return "HIGH";
  }

  // Health colors (higher is better)
  function getHealthColor(score) {
    if (score >= 75) return "#3a8a5c";
    if (score >= 50) return "#8a8a3a";
    if (score >= 25) return "#c49a3a";
    return "#b83a2a";
  }

  function getHealthLabel(score) {
    if (score >= 75) return "STRONG";
    if (score >= 50) return "SOLID";
    if (score >= 25) return "WATCH";
    return "WEAK";
  }

  // Basic markdown-to-summary helper (fallback when backend omits summary)
  function summarizeMarkdown(md, maxLen) {
    if (!md) return "";
    var text = md
      .replace(/```[\s\S]*?```/g, " ")
      .replace(/`[^`]*`/g, " ")
      .replace(/[#>*_\-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (!maxLen || text.length <= maxLen) return text;
    return text.slice(0, maxLen).trim() + "...";
  }

  /* ----------------------------------------------------------
     Ticker parsing
     ---------------------------------------------------------- */
  function parseTickers(raw) {
    var seen = {};
    var result = [];
    var parts = raw.split(",");
    for (var i = 0; i < parts.length; i++) {
      var t = parts[i].trim().toUpperCase();
      if (t.length > 0 && t.length <= 5 && /^[A-Z]+$/.test(t) && !seen[t]) {
        seen[t] = true;
        result.push(t);
      }
    }
    return result;
  }

  /* ----------------------------------------------------------
     Update chips + count + button state
     ---------------------------------------------------------- */
  var currentTickers = [];
  var isLoading = false;

  function refreshTickerUI() {
    currentTickers = parseTickers(tickerInput.value);

    // Count
    if (currentTickers.length > 0) {
      tickerCount.textContent = currentTickers.length + " symbol" + (currentTickers.length !== 1 ? "s" : "");
    } else {
      tickerCount.textContent = "";
    }

    // Chips
    tickerChips.innerHTML = "";
    for (var i = 0; i < currentTickers.length; i++) {
      var chip = document.createElement("span");
      chip.className = "ticker-chip";
      chip.textContent = currentTickers[i];
      tickerChips.appendChild(chip);
    }

    // Buttons
    analyzeBtn.disabled = currentTickers.length === 0 || isLoading;
    portfolioBtn.disabled = currentTickers.length === 0 || isLoading;
  }

  tickerInput.addEventListener("input", refreshTickerUI);

  /* ----------------------------------------------------------
     Keyboard shortcuts: Ctrl+Enter for analyze, Shift+Enter for portfolio
     ---------------------------------------------------------- */
  tickerInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (currentTickers.length > 0 && !isLoading) runAnalysis();
    }
    if (e.key === "Enter" && e.shiftKey && loggedInUser) {
      e.preventDefault();
      if (currentTickers.length > 0 && !isLoading) addToPortfolio(currentTickers);
    }
  });

  /* ----------------------------------------------------------
     API base URL
     ---------------------------------------------------------- */
  var API_BASE = "https://tower-relevant-puzzles-linked.trycloudflare.com";

  /* ----------------------------------------------------------
     Fetch stock + health data from backend
     Always resolves to {
       riskResults, riskErrors, healthResults, healthErrors
     }
     ---------------------------------------------------------- */
  function fetchStockData(tickers) {
    var tickerList = (Array.isArray(tickers) ? tickers : [tickers])
      .map(function (t) { return (t || "").trim().toUpperCase(); })
      .filter(Boolean);

    if (tickerList.length === 0) {
      return Promise.resolve({ riskResults: [], riskErrors: [], healthResults: [], healthErrors: [] });
    }

    function fetchJson(url, label) {
      return fetch(url, {
        method: "GET",
        headers: { "Cache-Control": "no-cache" },
      }).then(function (response) {
        if (!response.ok) throw new Error(label + " HTTP status " + response.status);
        return response.json();
      });
    }

    var ts = Date.now();

    // Multi-ticker: use batch endpoints for both risk + health
    if (tickerList.length > 1) {
      var riskUrl = API_BASE + "/stocks?tickers=" + encodeURIComponent(tickerList.join(",")) + "&ts=" + ts;
      var healthUrl = API_BASE + "/health-score?tickers=" + encodeURIComponent(tickerList.join(",")) + "&ts=" + ts;

      var riskPromise = fetchJson(riskUrl, "risk");
      var healthPromise = fetchJson(healthUrl, "health");

      return Promise.allSettled([riskPromise, healthPromise]).then(function (settled) {
        var riskResults = [];
        var riskErrors = [];
        var healthResults = [];
        var healthErrors = [];

        if (settled[0].status === "fulfilled") {
          var rd = settled[0].value;
          riskResults = Array.isArray(rd.results) ? rd.results : [];
          riskErrors = Array.isArray(rd.errors) ? rd.errors : [];
        } else {
          riskErrors = tickerList.map(function (t) { return { ticker: t, error: settled[0].reason.message }; });
        }

        if (settled[1].status === "fulfilled") {
          var hd = settled[1].value;
          healthResults = Array.isArray(hd.results) ? hd.results : [];
          healthErrors = Array.isArray(hd.errors) ? hd.errors : [];
        } else {
          healthErrors = tickerList.map(function (t) { return { ticker: t, error: settled[1].reason.message }; });
        }

        return { riskResults: riskResults, riskErrors: riskErrors, healthResults: healthResults, healthErrors: healthErrors };
      });
    }

    // Single ticker: call individual endpoints but wrap shapes
    var ticker = tickerList[0];
    var riskSingleUrl = API_BASE + "/stocks/" + ticker + "?ts=" + ts;
    var healthSingleUrl = API_BASE + "/health-score/" + ticker + "?ts=" + ts;

    var riskSingle = fetchJson(riskSingleUrl, "risk single").then(function (data) {
      return { results: [data], errors: [] };
    });
    var healthSingle = fetchJson(healthSingleUrl, "health single").then(function (data) {
      return { results: [data], errors: [] };
    });

    return Promise.allSettled([riskSingle, healthSingle]).then(function (settled) {
      var riskResults = [];
      var riskErrors = [];
      var healthResults = [];
      var healthErrors = [];

      if (settled[0].status === "fulfilled") {
        riskResults = settled[0].value.results;
        riskErrors = settled[0].value.errors;
      } else {
        riskErrors = [{ ticker: ticker, error: settled[0].reason.message }];
      }

      if (settled[1].status === "fulfilled") {
        healthResults = settled[1].value.results;
        healthErrors = settled[1].value.errors;
      } else {
        healthErrors = [{ ticker: ticker, error: settled[1].reason.message }];
      }

      return { riskResults: riskResults, riskErrors: riskErrors, healthResults: healthResults, healthErrors: healthErrors };
    });
  }

  /* ----------------------------------------------------------
     Fetch report (markdown + summary) for tickers
     ---------------------------------------------------------- */
  function fetchReport(tickers) {
    var tickerList = (Array.isArray(tickers) ? tickers : [tickers])
      .map(function (t) { return (t || "").trim().toUpperCase(); })
      .filter(Boolean);
    if (tickerList.length === 0) return Promise.resolve(null);

    var url = API_BASE + "/report?tickers=" + encodeURIComponent(tickerList.join(",")) + "&ts=" + Date.now();
    return fetch(url, {
      method: "GET",
      headers: { "Cache-Control": "no-cache" },
    })
      .then(function (response) {
        if (!response.ok) throw new Error("Report HTTP status " + response.status);
        return response.json();
      })
      .catch(function (error) {
        console.error("Error fetching report:", error);
        return null;
      });
  }

  /* ----------------------------------------------------------
     Auth state
     ---------------------------------------------------------- */
  var loggedInUser = null; // { phone, name }
  var authMode = "login"; // "login" | "register"
  var userFetchInFlight = false;

  function registerUser(phone, name) {
    return fetch(API_BASE + "/users", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
      },
      body: JSON.stringify({ phone: phone, name: name })
    }).then(function (resp) {
      if (!resp.ok) throw new Error("Register HTTP status " + resp.status);
      return resp.json();
    }).then(function (data) {
      return { phone: data.phone || phone, name: data.name || name, portfolio: [] };
    });
  }

  function fetchUser(phone) {
    if (userFetchInFlight) return Promise.reject(new Error("Please wait..."));
    userFetchInFlight = true;
    return fetch(API_BASE + "/users/" + encodeURIComponent(phone), {
      method: "GET",
      headers: { "Cache-Control": "no-cache" },
    })
      .then(function (resp) {
        userFetchInFlight = false;
        if (!resp.ok) throw new Error("User lookup HTTP status " + resp.status);
        return resp.json();
      })
      .then(function (data) {
        return {
          phone: data.phone || phone,
          name: data.name || phone,
          portfolio: Array.isArray(data.portfolio) ? data.portfolio : []
        };
      })
      .catch(function (err) {
        userFetchInFlight = false;
        throw err;
      });
  }

  function addToPortfolioRemote(phone, tickers) {
    return fetch(API_BASE + "/users/" + encodeURIComponent(phone) + "/portfolio", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
      },
      body: JSON.stringify({ tickers: tickers })
    }).then(function (resp) {
      if (!resp.ok) throw new Error("Portfolio HTTP status " + resp.status);
      return resp.json();
    });
  }

  function updateAuthBar() {
    authBar.innerHTML = "";
    if (loggedInUser) {
      var nameSpan = document.createElement("span");
      nameSpan.className = "auth-user-name";
      nameSpan.textContent = loggedInUser.name || loggedInUser.phone;

      var logoutBtn = document.createElement("button");
      logoutBtn.className = "auth-logout";
      logoutBtn.textContent = "Logout";
      logoutBtn.addEventListener("click", handleLogout);

      var wrap = document.createElement("div");
      wrap.style.display = "flex";
      wrap.style.alignItems = "center";
      wrap.style.gap = "12px";
      wrap.appendChild(nameSpan);
      wrap.appendChild(logoutBtn);
      authBar.appendChild(wrap);

      // Show portfolio UI
      portfolioBtn.style.display = "flex";
      portfolioHint.style.display = "";
    } else {
      var link = document.createElement("button");
      link.id = "auth-link";
      link.className = "auth-link";
      link.textContent = "Login / Register";
      link.addEventListener("click", openAuthModal);
      authBar.appendChild(link);

      // Hide portfolio UI
      portfolioBtn.style.display = "none";
      portfolioHint.style.display = "none";
      portfolioIndicator.style.display = "none";
    }
  }

  function handleLogout() {
    loggedInUser = null;
    portfolio = [];
    updateAuthBar();
    refreshTickerUI();
  }

  authLink.addEventListener("click", openAuthModal);

  /* ----------------------------------------------------------
     Auth Modal
     ---------------------------------------------------------- */
  function openAuthModal() {
    authMode = "login";
    refreshModal();
    authPhoneInput.value = "+";
    authNameInput.value = "";
    authModal.style.display = "flex";
    setTimeout(function () { authPhoneInput.focus(); }, 80);
  }

  function closeAuthModal() {
    authModal.style.display = "none";
  }

  function refreshModal() {
    if (authMode === "login") {
      modalTitle.textContent = "Login";
      modalDesc.textContent = "Enter your phone number to continue.";
      nameField.style.display = "none";
      modalSubmit.textContent = "Login";
      modalTogglePrompt.textContent = "No account?";
      modalToggle.textContent = "Register";
    } else {
      modalTitle.textContent = "Register";
      modalDesc.textContent = "Create an account to save your portfolio.";
      nameField.style.display = "";
      modalSubmit.textContent = "Register";
      modalTogglePrompt.textContent = "Already registered?";
      modalToggle.textContent = "Login";
    }
    validatePhoneField();
  }

  function sanitizePhone(raw) {
    var out = "";
    for (var i = 0; i < raw.length; i++) {
      var ch = raw.charAt(i);
      if (i === 0 && ch === "+") {
        out += "+";
      } else if (/\d/.test(ch)) {
        out += ch;
      }
    }
    if (out.charAt(0) !== "+") out = "+" + out.replace(/\+/g, "");
    var digits = out.slice(1).replace(/\D/g, "").slice(0, 13);
    return "+" + digits;
  }

  function isValidPhone(raw) {
    return /^\+\d{11,13}$/.test(raw);
  }

  function validatePhoneField() {
    var raw = authPhoneInput.value;
    var digitCount = raw.length > 0 ? raw.length - 1 : 0; // minus "+"
    phoneDigitCount.textContent = digitCount + "/11\u201313";

    var phoneOk = isValidPhone(raw);
    var nameOk = authMode === "login" || authNameInput.value.trim().length > 0;
    modalSubmit.disabled = !(phoneOk && nameOk);

    // Warn if typed but too short and not focused
    if (digitCount > 0 && digitCount < 11 && document.activeElement !== authPhoneInput) {
      phoneFormatHint.classList.add("warn");
    } else {
      phoneFormatHint.classList.remove("warn");
    }
  }

  authPhoneInput.addEventListener("input", function () {
    authPhoneInput.value = sanitizePhone(authPhoneInput.value);
    validatePhoneField();
  });

  authPhoneInput.addEventListener("blur", validatePhoneField);
  authPhoneInput.addEventListener("focus", validatePhoneField);
  authNameInput.addEventListener("input", validatePhoneField);

  // Enter key submits modal
  function modalKeydown(e) {
    if (e.key === "Enter" && !modalSubmit.disabled) {
      e.preventDefault();
      submitAuth();
    }
    if (e.key === "Escape") {
      closeAuthModal();
    }
  }
  authPhoneInput.addEventListener("keydown", modalKeydown);
  authNameInput.addEventListener("keydown", modalKeydown);

  function submitAuth() {
    var phone = authPhoneInput.value;
    if (!isValidPhone(phone)) return;
    if (authMode === "register") {
      var name = authNameInput.value.trim();
      if (!name) return;
      registerUser(phone, name)
        .then(function (user) {
          loggedInUser = user;
          portfolio = [];
          closeAuthModal();
          updateAuthBar();
          refreshPortfolioUI();
          refreshTickerUI();
        })
        .catch(function (err) {
          console.error("Register failed", err);
          alert("Register failed: " + err.message);
        });
    } else {
      fetchUser(phone)
        .then(function (user) {
          loggedInUser = user;
          portfolio = (user.portfolio || []).map(function (p) { return p.ticker; });
          closeAuthModal();
          updateAuthBar();
          refreshPortfolioUI();
          refreshTickerUI();
        })
        .catch(function (err) {
          console.error("Login failed", err);
          alert("Login failed: " + err.message);
        });
    }
  }

  modalSubmit.addEventListener("click", submitAuth);
  modalBackdrop.addEventListener("click", closeAuthModal);

  // Escape to close
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && authModal.style.display !== "none") {
      closeAuthModal();
    }
  });

  modalToggle.addEventListener("click", function () {
    authMode = authMode === "login" ? "register" : "login";
    authPhoneInput.value = "+";
    authNameInput.value = "";
    refreshModal();
    setTimeout(function () {
      if (authMode === "register") {
        authNameInput.focus();
      } else {
        authPhoneInput.focus();
      }
    }, 80);
  });

  /* ----------------------------------------------------------
     Portfolio
     ---------------------------------------------------------- */
  var portfolio = [];

  function addToPortfolio(tickers) {
    if (!loggedInUser) return;
    var clean = tickers.map(function (t) { return (t || "").toUpperCase(); }).filter(Boolean);
    if (clean.length === 0) return;
    addToPortfolioRemote(loggedInUser.phone, clean)
      .then(function (added) {
        var merged = {};
        for (var i = 0; i < portfolio.length; i++) merged[portfolio[i]] = true;
        for (var j = 0; j < clean.length; j++) merged[clean[j]] = true;
        portfolio = Object.keys(merged);
        refreshPortfolioUI();
      })
      .catch(function (err) {
        console.error("Add to portfolio failed", err);
        alert("Could not add to portfolio: " + err.message);
      });
  }

  function refreshPortfolioUI() {
    if (!loggedInUser || portfolio.length === 0) {
      portfolioIndicator.style.display = "none";
      return;
    }
    portfolioIndicator.style.display = "";
    portfolioLabel.textContent = "Portfolio (" + portfolio.length + ")";
    portfolioChips.innerHTML = "";
    for (var i = 0; i < portfolio.length; i++) {
      var chip = document.createElement("span");
      chip.className = "portfolio-chip";
      chip.textContent = portfolio[i];
      portfolioChips.appendChild(chip);
    }
  }

  portfolioBtn.addEventListener("click", function () {
    if (currentTickers.length > 0 && !isLoading) {
      addToPortfolio(currentTickers);
    }
  });

  /* ----------------------------------------------------------
     Run Analysis
     ---------------------------------------------------------- */
  var progressInterval = null;
  var currentResult = null;
  var currentErrors = null;
  var lastReportMarkdown = null;
  var lastReportSummary = null;

  function runAnalysis() {
    var tickers = currentTickers.slice();
    var reportPromise = fetchReport(tickers);
    lastReportMarkdown = null;
    lastReportSummary = null;
    reportSummary.style.display = "none";
    isLoading = true;
    analyzeBtn.classList.add("is-loading");
    analyzeBtn.disabled = true;
    tickerInput.disabled = true;
    shortcutHint.style.display = "none";
    if (loggedInUser) {
      portfolioBtn.style.display = "none";
      portfolioHint.style.display = "none";
    }
    resultsSec.style.display = "none";
    resultsSec.classList.remove("visible");
    skeletonSec.style.display = "block";

    var progress = 0;
    progressFill.style.width = "0%";
    btnLabel.textContent = "Analyzing";

    progressInterval = setInterval(function () {
      progress += Math.random() * 8 + 2;
      if (progress > 90) progress = 90;
      progressFill.style.width = progress + "%";

      var dots = ".".repeat(Math.floor((progress / 25) % 4));
      btnLabel.textContent = "Analyzing" + dots;
    }, 300);

    fetchStockData(tickers).then(function (payload) {
      clearInterval(progressInterval);
      progressFill.style.width = "100%";
      btnLabel.textContent = "Analyzing...";

      setTimeout(function () {
        var riskResults = Array.isArray(payload.riskResults) ? payload.riskResults : [];
        var riskErrors = Array.isArray(payload.riskErrors) ? payload.riskErrors : [];
        var healthResults = Array.isArray(payload.healthResults) ? payload.healthResults : [];
        var healthErrors = Array.isArray(payload.healthErrors) ? payload.healthErrors : [];

        var healthMap = {};
        for (var h = 0; h < healthResults.length; h++) {
          healthMap[healthResults[h].ticker] = healthResults[h];
        }

        currentResult = riskResults.map(function (r) {
          return Object.assign({}, r, { health: healthMap[r.ticker] || null });
        });

        // Merge and dedupe errors by ticker
        var mergedErrors = {};
        var allErrs = riskErrors.concat(healthErrors);
        for (var e = 0; e < allErrs.length; e++) {
          var te = (allErrs[e].ticker || "").toUpperCase();
          if (!te) continue;
          if (!mergedErrors[te]) mergedErrors[te] = allErrs[e];
        }
        currentErrors = Object.keys(mergedErrors).map(function (k) { return mergedErrors[k]; });
        isLoading = false;
        analyzeBtn.classList.remove("is-loading");
        progressFill.style.width = "0%";
        btnLabel.textContent = "Run Analysis";
        tickerInput.disabled = false;
        shortcutHint.style.display = "";
        if (loggedInUser) {
          portfolioBtn.style.display = "flex";
          portfolioHint.style.display = "";
        }
        skeletonSec.style.display = "none";
        refreshTickerUI();

        // Align background color to the first slide if present
        canvasRiskScore = currentResult.length > 0 ? currentResult[0].composite_fraud_risk_score : null;

        renderResults(currentResult, currentErrors);

        // Report summary (async, non-blocking)
        reportSummaryText.textContent = "Loading report summary...";
        reportSummary.classList.add("loading");
        reportSummary.style.display = "block";

        reportPromise.then(function (report) {
          if (report && report.report_markdown) {
            lastReportMarkdown = report.report_markdown;
            lastReportSummary = report.summary || summarizeMarkdown(report.report_markdown, 420);
            reportSummaryText.textContent = lastReportSummary || "Report ready.";
            reportSummary.classList.remove("loading");
          } else {
            reportSummaryText.textContent = "Report unavailable.";
            reportSummary.classList.add("loading");
          }
        });
      }, 300);
    });
  }

  analyzeBtn.addEventListener("click", function () {
    if (currentTickers.length > 0 && !isLoading) runAnalysis();
  });

  /* ----------------------------------------------------------
     Render results — carousel
     ---------------------------------------------------------- */
  var allSlides = [];   // array of DOM elements
  var carouselIndex = 0;
  var carouselAnimating = false;

  function renderResults(stocks, errors) {
    stockCardsContainer.innerHTML = "";
    allSlides = [];
    carouselIndex = 0;

    // Build stock cards
    for (var i = 0; i < stocks.length; i++) {
      var card = buildStockCard(stocks[i]);
      card.className = "carousel-slide results-divider stock-card";
      card.setAttribute("data-risk", String(stocks[i].composite_fraud_risk_score || 0));
      allSlides.push(card);
      stockCardsContainer.appendChild(card);
    }

    // Build error cards
    for (var e = 0; e < errors.length; e++) {
      var errCard = buildErrorCard(errors[e]);
      errCard.className = "carousel-slide results-divider stock-card stock-card-error";
      errCard.setAttribute("data-risk", "");
      allSlides.push(errCard);
      stockCardsContainer.appendChild(errCard);
    }

    var total = allSlides.length;

    // Show/hide carousel nav
    if (total > 1) {
      carouselNav.style.display = "flex";
      carouselHint.style.display = "";
      buildCarouselDots(total);
    } else {
      carouselNav.style.display = "none";
      carouselHint.style.display = "none";
    }

    // Show first slide, hide rest
    for (var s = 0; s < allSlides.length; s++) {
      allSlides[s].style.display = s === 0 ? "" : "none";
      allSlides[s].style.opacity = "1";
      allSlides[s].style.transform = "translateX(0)";
    }

    updateCarouselUI();
    setCanvasColorForSlide(0);

    // Show results with fade-in
    resultsSec.style.display = "block";
    requestAnimationFrame(function () {
      resultsSec.classList.add("visible");
      resultsSec.scrollIntoView({ behavior: "smooth", block: "start" });

      // Animate score for first visible card
      animateVisibleCard(0);
    });
  }

  function setCanvasColorForSlide(idx) {
    var slide = allSlides[idx];
    if (!slide) {
      canvasRiskScore = null;
      return;
    }
    var riskAttr = slide.getAttribute("data-risk");
    canvasRiskScore = riskAttr ? parseFloat(riskAttr) : null;
  }

  function buildStockCard(s) {
    var score = s.composite_fraud_risk_score;
    var color = getScoreColor(score);
    var label = getScoreLabel(score);
    var h = s.health || null;
    var healthScore = h ? h.composite_stock_health_score : null;
    var healthColor = healthScore !== null && healthScore !== undefined ? getHealthColor(healthScore) : "#3a3a3f";
    var healthLabel = healthScore !== null && healthScore !== undefined ? getHealthLabel(healthScore) : "N/A";

    var card = document.createElement("div");

    // Header row
    var header = document.createElement("div");
    header.className = "score-header";

    var tickerLabel = document.createElement("span");
    tickerLabel.className = "section-label stock-ticker-label";
    tickerLabel.textContent = s.ticker + (s.company_name ? " \u2014 " + s.company_name : "");

    var sevLabel = document.createElement("span");
    sevLabel.className = "score-severity-label";
    sevLabel.textContent = label;
    sevLabel.style.color = color;

    header.appendChild(tickerLabel);
    header.appendChild(sevLabel);
    card.appendChild(header);

    // Score display
    var scoreDisplay = document.createElement("div");
    scoreDisplay.className = "score-display";

    var scoreNum = document.createElement("span");
    scoreNum.className = "score-number";
    scoreNum.style.color = color;
    scoreNum.textContent = "0";
    scoreNum.setAttribute("data-target", String(Math.round(score)));

    var scoreDenom = document.createElement("span");
    scoreDenom.className = "score-denominator";
    scoreDenom.textContent = "/ 100";

    scoreDisplay.appendChild(scoreNum);
    scoreDisplay.appendChild(scoreDenom);
    card.appendChild(scoreDisplay);

    // Score bar
    var barTrack = document.createElement("div");
    barTrack.className = "score-bar-track";

    var barFill = document.createElement("div");
    barFill.className = "score-bar-fill";
    barFill.setAttribute("data-target", String(score));
    barFill.style.background = color;

    barTrack.appendChild(barFill);
    card.appendChild(barTrack);

    // Markers
    var markers = document.createElement("div");
    markers.className = "score-markers";
    var markerVals = [0, 25, 50, 75, 100];
    for (var m = 0; m < markerVals.length; m++) {
      var sp = document.createElement("span");
      sp.textContent = String(markerVals[m]);
      markers.appendChild(sp);
    }
    card.appendChild(markers);

    // Metrics
    var metricsWrap = document.createElement("div");
    metricsWrap.className = "stock-metrics";

    var metricsTitle = document.createElement("div");
    metricsTitle.className = "factors-label-wrap";
    var metricsTitleSpan = document.createElement("span");
    metricsTitleSpan.className = "section-label";
    metricsTitleSpan.textContent = "Key Metrics";
    metricsTitle.appendChild(metricsTitleSpan);
    metricsWrap.appendChild(metricsTitle);

    var metrics = [
      { name: "Beneish M-Score",  value: s.m_score },
      { name: "Altman Z-Score",   value: s.z_score },
      { name: "Accruals Ratio",   value: s.accruals_ratio }
    ];

    for (var j = 0; j < metrics.length; j++) {
      var metricRow = document.createElement("div");
      metricRow.className = "metric-row";

      var metricDot = document.createElement("div");
      metricDot.className = "factor-dot";
      metricDot.style.background = getMetricDotColor(metrics[j].name, metrics[j].value);

      var metricLabel = document.createElement("span");
      metricLabel.className = "factor-label";
      metricLabel.textContent = metrics[j].name;

      var metricValue = document.createElement("span");
      metricValue.className = "metric-value";
      metricValue.textContent = formatMetric(metrics[j].value);

      metricRow.appendChild(metricDot);
      metricRow.appendChild(metricLabel);
      metricRow.appendChild(metricValue);
      metricsWrap.appendChild(metricRow);
    }

    card.appendChild(metricsWrap);

    // Health block
    var healthWrap = document.createElement("div");
    healthWrap.className = "health-block";

    var healthHeader = document.createElement("div");
    healthHeader.className = "health-score-row";

    var healthLabelEl = document.createElement("span");
    healthLabelEl.className = "section-label";
    healthLabelEl.textContent = "Stock Health";

    var healthSeverity = document.createElement("span");
    healthSeverity.className = "health-severity-label";
    healthSeverity.style.color = healthColor;
    healthSeverity.textContent = healthLabel;

    healthHeader.appendChild(healthLabelEl);
    healthHeader.appendChild(healthSeverity);
    healthWrap.appendChild(healthHeader);

    var healthDisplay = document.createElement("div");
    healthDisplay.className = "score-display";

    var healthNum = document.createElement("span");
    healthNum.className = "score-number health-score-number";
    healthNum.style.color = healthColor;
    if (healthScore !== null && healthScore !== undefined) {
      healthNum.textContent = "0";
      healthNum.setAttribute("data-target", String(Math.round(healthScore)));
    } else {
      healthNum.textContent = "N/A";
    }

    var healthDenom = document.createElement("span");
    healthDenom.className = "score-denominator";
    healthDenom.textContent = healthScore !== null && healthScore !== undefined ? "/ 100" : "";

    healthDisplay.appendChild(healthNum);
    healthDisplay.appendChild(healthDenom);
    healthWrap.appendChild(healthDisplay);

    var healthBarTrack = document.createElement("div");
    healthBarTrack.className = "score-bar-track";
    var healthBarFill = document.createElement("div");
    healthBarFill.className = "score-bar-fill";
    healthBarFill.style.background = healthColor;
    if (healthScore !== null && healthScore !== undefined) {
      healthBarFill.setAttribute("data-target", String(healthScore));
    }
    healthBarTrack.appendChild(healthBarFill);
    healthWrap.appendChild(healthBarTrack);

    var healthMarkers = document.createElement("div");
    healthMarkers.className = "score-markers";
    var healthMarkerVals = [0, 25, 50, 75, 100];
    for (var hm = 0; hm < healthMarkerVals.length; hm++) {
      var hsp = document.createElement("span");
      hsp.textContent = String(healthMarkerVals[hm]);
      healthMarkers.appendChild(hsp);
    }
    healthWrap.appendChild(healthMarkers);

    // Health metrics list (if available)
    if (h) {
      var healthMetrics = [
        { name: "Sharpe", value: h.sharpe },
        { name: "Sortino", value: h.sortino },
        { name: "Alpha", value: h.alpha },
        { name: "Beta", value: h.beta },
        { name: "VaR 95%", value: h.var_95 },
        { name: "CVaR 95%", value: h.cvar_95 },
        { name: "Max Drawdown", value: h.max_drawdown },
        { name: "Volatility", value: h.volatility }
      ];

      for (var hx = 0; hx < healthMetrics.length; hx++) {
        var hRow = document.createElement("div");
        hRow.className = "metric-row";

        var hDot = document.createElement("div");
        hDot.className = "factor-dot";
        hDot.style.background = healthColor;

        var hLabel = document.createElement("span");
        hLabel.className = "factor-label";
        hLabel.textContent = healthMetrics[hx].name;

        var hVal = document.createElement("span");
        hVal.className = "metric-value";
        hVal.textContent = healthMetrics[hx].value === null || healthMetrics[hx].value === undefined
          ? "N/A"
          : Number(healthMetrics[hx].value).toFixed(4);

        hRow.appendChild(hDot);
        hRow.appendChild(hLabel);
        hRow.appendChild(hVal);
        healthWrap.appendChild(hRow);
      }
    }

    card.appendChild(healthWrap);
    return card;
  }

  function buildErrorCard(err) {
    var card = document.createElement("div");
    card.innerHTML =
      '<div class="score-header">' +
        '<span class="section-label stock-ticker-label">' + err.ticker + '</span>' +
        '<span class="score-severity-label" style="color:#b83a2a">ERROR</span>' +
      '</div>' +
      '<p class="summary-text" style="margin-top:8px;">Could not retrieve data: ' + err.error + '</p>';
    return card;
  }

  /* ----------------------------------------------------------
     Carousel navigation
     ---------------------------------------------------------- */
  function buildCarouselDots(total) {
    carouselDots.innerHTML = "";
    for (var i = 0; i < total; i++) {
      var dot = document.createElement("button");
      dot.className = "carousel-dot" + (i === 0 ? " active" : "");
      dot.setAttribute("aria-label", "Go to result " + (i + 1));
      dot.setAttribute("data-index", String(i));
      dot.addEventListener("click", function () {
        var idx = parseInt(this.getAttribute("data-index"), 10);
        if (idx !== carouselIndex && !carouselAnimating) {
          navigateCarousel(idx > carouselIndex ? "right" : "left", idx);
        }
      });
      carouselDots.appendChild(dot);
    }
  }

  function updateCarouselUI() {
    var total = allSlides.length;
    if (total <= 1) return;

    carouselCounter.innerHTML = (carouselIndex + 1) + ' <span class="dim">/ ' + total + '</span>';

    var dots = carouselDots.querySelectorAll(".carousel-dot");
    for (var i = 0; i < dots.length; i++) {
      if (i === carouselIndex) {
        dots[i].classList.add("active");
      } else {
        dots[i].classList.remove("active");
      }
    }
  }

  function navigateCarousel(direction, targetIndex) {
    if (carouselAnimating || allSlides.length <= 1) return;
    var total = allSlides.length;

    if (targetIndex === undefined) {
      if (direction === "right") {
        targetIndex = (carouselIndex + 1) % total;
      } else {
        targetIndex = (carouselIndex - 1 + total) % total;
      }
    }

    carouselAnimating = true;
    var currentSlide = allSlides[carouselIndex];
    var xOut = direction === "right" ? "-12px" : "12px";

    // Fade out current
    currentSlide.style.opacity = "0";
    currentSlide.style.transform = "translateX(" + xOut + ")";

    setTimeout(function () {
      currentSlide.style.display = "none";
      currentSlide.style.opacity = "1";
      currentSlide.style.transform = "translateX(0)";

      carouselIndex = targetIndex;

      var nextSlide = allSlides[carouselIndex];
      var xIn = direction === "right" ? "12px" : "-12px";
      nextSlide.style.display = "";
      nextSlide.style.opacity = "0";
      nextSlide.style.transform = "translateX(" + xIn + ")";

      // Trigger reflow then animate in
      void nextSlide.offsetWidth;
      nextSlide.style.opacity = "1";
      nextSlide.style.transform = "translateX(0)";

      updateCarouselUI();
      setCanvasColorForSlide(carouselIndex);
      animateVisibleCard(carouselIndex);

      setTimeout(function () {
        carouselAnimating = false;
      }, 260);
    }, 250);
  }

  carouselPrev.addEventListener("click", function () {
    navigateCarousel("left");
  });

  carouselNext.addEventListener("click", function () {
    navigateCarousel("right");
  });

  // Arrow key navigation
  document.addEventListener("keydown", function (e) {
    if (allSlides.length <= 1) return;
    if (resultsSec.style.display === "none") return;
    // Don't capture if user is typing in an input
    if (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT") return;

    if (e.key === "ArrowLeft") navigateCarousel("left");
    if (e.key === "ArrowRight") navigateCarousel("right");
  });

  function animateVisibleCard(idx) {
    var card = allSlides[idx];
    if (!card) return;
    var scoreEls = card.querySelectorAll(".score-number[data-target]");
    var barEls = card.querySelectorAll(".score-bar-fill[data-target]");
    for (var k = 0; k < scoreEls.length; k++) {
      // Reset before animating
      scoreEls[k].textContent = "0";
      if (barEls[k]) barEls[k].style.width = "0%";
      animateScoreElement(scoreEls[k], barEls[k]);
    }
  }

  /* ----------------------------------------------------------
     Metric helpers
     ---------------------------------------------------------- */
  function formatMetric(val) {
    if (val === null || val === undefined) return "N/A";
    return Number(val).toFixed(4);
  }

  function getMetricDotColor(name, val) {
    if (name === "Beneish M-Score") {
      return val < -1.78 ? "#3a8a5c" : val < -1.0 ? "#c49a3a" : "#b83a2a";
    }
    if (name === "Altman Z-Score") {
      return val > 2.99 ? "#3a8a5c" : val > 1.81 ? "#c49a3a" : "#b83a2a";
    }
    if (name === "Accruals Ratio") {
      return Math.abs(val) < 0.05 ? "#3a8a5c" : Math.abs(val) < 0.10 ? "#c49a3a" : "#b83a2a";
    }
    return "#7a7a84";
  }

  /* ----------------------------------------------------------
     Animated score counter + bar (per element)
     ---------------------------------------------------------- */
  function animateScoreElement(numEl, barEl) {
    var targetScore = parseInt(numEl.getAttribute("data-target"), 10);
    var duration = 1200;
    var startTime = 0;

    function tick(now) {
      if (!startTime) startTime = now;
      var elapsed = now - startTime;
      var progress = Math.min(elapsed / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);

      var display = Math.round(eased * targetScore);
      numEl.textContent = String(display);
      if (barEl) {
        barEl.style.width = (eased * targetScore) + "%";
      }

      if (progress < 1) {
        requestAnimationFrame(tick);
      }
    }

    setTimeout(function () {
      requestAnimationFrame(tick);
    }, 200);
  }

  /* ----------------------------------------------------------
     Download report
     ---------------------------------------------------------- */
  downloadBtn.addEventListener("click", function () {
    if (!currentResult || currentResult.length === 0) return;
    downloadBtn.disabled = true;
    downloadLabel.textContent = "Preparing report...";

    setTimeout(function () {
      var tickerSet = {};
      var tickers = [];
      if (Array.isArray(currentResult)) {
        for (var t = 0; t < currentResult.length; t++) {
          var tk = currentResult[t].ticker;
          if (tk && !tickerSet[tk]) { tickerSet[tk] = true; tickers.push(tk); }
        }
      }
      if (Array.isArray(currentErrors)) {
        for (var ce = 0; ce < currentErrors.length; ce++) {
          var et = currentErrors[ce].ticker;
          if (et && !tickerSet[et]) { tickerSet[et] = true; tickers.push(et); }
        }
      }
      if (tickers.length === 0) tickers = ["report"];

      if (lastReportMarkdown) {
        var blobMd = new Blob([lastReportMarkdown], { type: "text/markdown" });
        var urlMd = URL.createObjectURL(blobMd);
        var aMd = document.createElement("a");
        aMd.href = urlMd;
        aMd.download = "report-" + tickers.join("-") + "-" + Date.now() + ".md";
        aMd.click();
        URL.revokeObjectURL(urlMd);
      } else {
        var lines = [
          "FRAUD RISK ANALYSIS REPORT",
          "=".repeat(40),
          "",
          "Generated: " + new Date().toISOString().split("T")[0],
          "Tickers: " + tickers.join(", "),
          ""
        ];

        for (var i = 0; i < currentResult.length; i++) {
          var s = currentResult[i];
          lines.push("");
          lines.push(s.ticker + (s.company_name ? " \u2014 " + s.company_name : ""));
          lines.push("-".repeat(40));
          lines.push("Composite Fraud Risk Score: " + s.composite_fraud_risk_score.toFixed(2) + " / 100");
          if (s.health && s.health.composite_stock_health_score !== undefined) {
            lines.push("Composite Stock Health Score: " + s.health.composite_stock_health_score.toFixed(2) + " / 100");
          }
          lines.push("Beneish M-Score:            " + s.m_score.toFixed(4));
          lines.push("Altman Z-Score:             " + s.z_score.toFixed(4));
          lines.push("Accruals Ratio:             " + s.accruals_ratio.toFixed(4));
        }

        lines.push("");
        lines.push("DISCLAIMER");
        lines.push("-".repeat(40));
        lines.push("This report is generated for informational purposes only.");
        lines.push("It does not constitute financial or legal advice.");
        lines.push("Conduct independent due diligence before making any decisions.");

        var blob = new Blob([lines.join("\n")], { type: "text/plain" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "risk-report-" + tickers.join("-") + "-" + Date.now() + ".txt";
        a.click();
        URL.revokeObjectURL(url);
      }

      downloadBtn.disabled = false;
      downloadLabel.textContent = "Download full report";
    }, 800);
  });

  /* ==========================================================
     Background Canvas — Network Pulse + Stars
     ========================================================== */

  // --- Color utilities ---

  var COLOR_NEUTRAL = [60, 62, 70];
  var COLOR_STOPS = [
    { score: 0,   color: [58, 138, 92] },
    { score: 25,  color: [58, 138, 92] },
    { score: 40,  color: [138, 138, 58] },
    { score: 60,  color: [196, 154, 58] },
    { score: 75,  color: [196, 100, 42] },
    { score: 100, color: [184, 58, 42] }
  ];

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function getTargetColor(score) {
    if (score === null || score === undefined) return COLOR_NEUTRAL.slice();
    var s = clamp(score, 0, 100);
    for (var i = 0; i < COLOR_STOPS.length - 1; i++) {
      var a = COLOR_STOPS[i];
      var b = COLOR_STOPS[i + 1];
      if (s >= a.score && s <= b.score) {
        var t = (s - a.score) / (b.score - a.score);
        return [
          a.color[0] + (b.color[0] - a.color[0]) * t,
          a.color[1] + (b.color[1] - a.color[1]) * t,
          a.color[2] + (b.color[2] - a.color[2]) * t
        ];
      }
    }
    var last = COLOR_STOPS[COLOR_STOPS.length - 1].color;
    return last.slice();
  }

  function lerpRGB(current, target, speed) {
    current[0] += (target[0] - current[0]) * speed;
    current[1] += (target[1] - current[1]) * speed;
    current[2] += (target[2] - current[2]) * speed;
  }

  // --- Lifecycle opacity ---
  function lifecycleOpacity(age, lifetime) {
    var t = age / lifetime;
    if (t < 0 || t > 1) return 0;
    if (t < 0.10) return t / 0.10;
    if (t < 0.60) return 1;
    return 1 - (t - 0.60) / 0.40;
  }

  // --- Config ---
  var MAX_NODES           = 65;
  var NODE_SPAWN_INTERVAL = 0.6;
  var CONN_SPAWN_INTERVAL = 0.4;
  var NODE_RADIUS_MIN     = 1.5;
  var NODE_RADIUS_MAX     = 3;
  var NODE_LIFETIME_MIN   = 10;
  var NODE_LIFETIME_MAX   = 22;
  var CONN_FADE_IN        = 1.5;
  var MAX_CONNECTIONS     = 80;
  var LINE_WIDTH          = 1.2;
  var MAX_LINE_ALPHA      = 0.38;
  var MAX_NODE_ALPHA      = 0.50;
  var MAX_GLOW_ALPHA      = 0.14;
  var DRIFT_SPEED         = 0.004;
  var MIN_NODE_DIST       = 0.08;
  var DIST_REF            = 0.25;

  // --- Stars config ---
  var STAR_COUNT           = 120;
  var STAR_RADIUS_MIN      = 0.3;
  var STAR_RADIUS_MAX      = 1.2;
  var STAR_BASE_ALPHA      = 0.25;
  var STAR_TWINKLE_COUNT   = 30;  // how many stars twinkle
  var STAR_TWINKLE_SPEED_MIN = 0.3;
  var STAR_TWINKLE_SPEED_MAX = 1.2;

  // --- Canvas setup ---

  var canvas = document.getElementById("bg-canvas");
  var ctx = canvas.getContext("2d", { alpha: false });
  var canvasRiskScore = null; // updated when analysis completes

  var prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var w = 0, h = 0;
  var currentColor = COLOR_NEUTRAL.slice();
  var nextId = 0;
  var nodes = [];
  var connections = [];
  var nodeMap = {};
  var lastNodeSpawn = 0;
  var lastConnSpawn = 0;

  // --- Stars data ---
  var stars = [];

  function generateStars() {
    stars = [];
    for (var i = 0; i < STAR_COUNT; i++) {
      var twinkle = i < STAR_TWINKLE_COUNT;
      stars.push({
        x: Math.random(),
        y: Math.random(),
        r: STAR_RADIUS_MIN + Math.random() * (STAR_RADIUS_MAX - STAR_RADIUS_MIN),
        baseAlpha: STAR_BASE_ALPHA * (0.4 + Math.random() * 0.6),
        twinkle: twinkle,
        twinkleSpeed: twinkle
          ? STAR_TWINKLE_SPEED_MIN + Math.random() * (STAR_TWINKLE_SPEED_MAX - STAR_TWINKLE_SPEED_MIN)
          : 0,
        twinkleOffset: Math.random() * Math.PI * 2
      });
    }
  }

  function drawStars(elapsed) {
    for (var i = 0; i < stars.length; i++) {
      var s = stars[i];
      var alpha = s.baseAlpha;

      if (s.twinkle && !prefersReducedMotion) {
        // Gentle sine-wave twinkle
        var t = Math.sin(elapsed * s.twinkleSpeed + s.twinkleOffset);
        alpha = s.baseAlpha * (0.35 + 0.65 * ((t + 1) / 2));
      }

      if (alpha < 0.01) continue;

      var px = s.x * w;
      var py = s.y * h;

      ctx.fillStyle = "rgba(200, 200, 210, " + alpha.toFixed(3) + ")";
      ctx.beginPath();
      ctx.arc(px, py, s.r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // --- Network node functions ---

  function resize() {
    var cw = canvas.clientWidth;
    var ch = canvas.clientHeight;
    if (cw === 0 || ch === 0) return;
    w = cw;
    h = ch;
    canvas.width = w;
    canvas.height = h;
  }

  function createNode(time) {
    return {
      id: nextId++,
      x: Math.random(),
      y: Math.random(),
      birthTime: time,
      lifetime: NODE_LIFETIME_MIN + Math.random() * (NODE_LIFETIME_MAX - NODE_LIFETIME_MIN),
      radius: NODE_RADIUS_MIN + Math.random() * (NODE_RADIUS_MAX - NODE_RADIUS_MIN),
      driftX: (Math.random() - 0.5) * 2 * DRIFT_SPEED,
      driftY: (Math.random() - 0.5) * 2 * DRIFT_SPEED
    };
  }

  function isTooClose(x, y, elapsed) {
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      var age = elapsed - n.birthTime;
      if (age > n.lifetime) continue;
      var nx = n.x + n.driftX * age;
      var ny = n.y + n.driftY * age;
      var dx = x - nx;
      var dy = y - ny;
      if (dx * dx + dy * dy < MIN_NODE_DIST * MIN_NODE_DIST) return true;
    }
    return false;
  }

  function spawnNode(time) {
    if (nodes.length >= MAX_NODES) return;
    for (var attempt = 0; attempt < 8; attempt++) {
      var n = createNode(time);
      if (!isTooClose(n.x, n.y, time)) {
        nodes.push(n);
        nodeMap[n.id] = n;
        return;
      }
    }
  }

  function removeNode(idx) {
    var n = nodes[idx];
    delete nodeMap[n.id];
    nodes.splice(idx, 1);
  }

  function nodePos(n, elapsed) {
    var age = elapsed - n.birthTime;
    return [(n.x + n.driftX * age) * w, (n.y + n.driftY * age) * h];
  }

  function connectionExists(idA, idB) {
    for (var i = 0; i < connections.length; i++) {
      var c = connections[i];
      if ((c.idA === idA && c.idB === idB) || (c.idA === idB && c.idB === idA)) return true;
    }
    return false;
  }

  function trySpawnConnection(elapsed) {
    if (connections.length >= MAX_CONNECTIONS) return;
    if (nodes.length < 2) return;

    var aIdx = (Math.random() * nodes.length) | 0;
    var a = nodes[aIdx];
    var aAge = elapsed - a.birthTime;
    var aOp = lifecycleOpacity(aAge, a.lifetime);
    if (aOp < 0.5) return;

    var aPos = nodePos(a, elapsed);
    var ax = aPos[0], ay = aPos[1];
    var diag = Math.sqrt(w * w + h * h);
    var refPx = DIST_REF * diag;

    var candidates = [];
    var totalWeight = 0;

    for (var i = 0; i < nodes.length; i++) {
      if (i === aIdx) continue;
      var b = nodes[i];
      var bAge = elapsed - b.birthTime;
      var bOp = lifecycleOpacity(bAge, b.lifetime);
      if (bOp < 0.3) continue;
      if (connectionExists(a.id, b.id)) continue;

      var bPos = nodePos(b, elapsed);
      var dx = ax - bPos[0];
      var dy = ay - bPos[1];
      var dist = Math.sqrt(dx * dx + dy * dy);
      var weight = Math.exp(-dist / refPx);
      candidates.push({ node: b, weight: weight });
      totalWeight += weight;
    }

    if (candidates.length === 0 || totalWeight <= 0) return;

    var pick = Math.random() * totalWeight;
    var chosen = candidates[0].node;
    for (var j = 0; j < candidates.length; j++) {
      pick -= candidates[j].weight;
      if (pick <= 0) {
        chosen = candidates[j].node;
        break;
      }
    }

    var aRemaining = a.lifetime - aAge;
    var bRemaining = chosen.lifetime - (elapsed - chosen.birthTime);
    var connLife = Math.min(aRemaining, bRemaining);
    if (connLife < 2) return;

    connections.push({ idA: a.id, idB: chosen.id, birthTime: elapsed, lifetime: connLife });
  }

  // Seed initial nodes
  function seedNodes() {
    var count = 40;
    for (var i = 0; i < count; i++) {
      var stagger = -(Math.random() * NODE_LIFETIME_MAX * 0.5);
      var placed = false;
      for (var attempt = 0; attempt < 10; attempt++) {
        var n = createNode(stagger);
        var tooClose = false;
        for (var j = 0; j < nodes.length; j++) {
          var other = nodes[j];
          var dx = n.x - other.x;
          var dy = n.y - other.y;
          if (dx * dx + dy * dy < MIN_NODE_DIST * MIN_NODE_DIST) {
            tooClose = true;
            break;
          }
        }
        if (!tooClose) {
          nodes.push(n);
          nodeMap[n.id] = n;
          placed = true;
          break;
        }
      }
      if (!placed) {
        var fallback = createNode(stagger);
        nodes.push(fallback);
        nodeMap[fallback.id] = fallback;
      }
    }
  }

  function seedConnections() {
    var sw = w || 1200;
    var sh = h || 800;
    var diag = Math.sqrt(sw * sw + sh * sh);
    var refPx = DIST_REF * diag;
    var attempts = 100;
    var spawned = 0;

    while (attempts > 0 && spawned < 20) {
      attempts--;
      var aIdx = (Math.random() * nodes.length) | 0;
      var bIdx = (Math.random() * nodes.length) | 0;
      if (aIdx === bIdx) continue;
      var a = nodes[aIdx];
      var b = nodes[bIdx];
      if (connectionExists(a.id, b.id)) continue;

      var ax = a.x * sw;
      var ay = a.y * sh;
      var bx = b.x * sw;
      var by = b.y * sh;
      var dx = ax - bx;
      var dy = ay - by;
      var dist = Math.sqrt(dx * dx + dy * dy);
      var prob = Math.exp(-dist / refPx);
      if (Math.random() > prob) continue;

      var stagger = -(Math.random() * 6);
      var aAge = -a.birthTime;
      var aRemaining = a.lifetime - aAge;
      var bRemaining = b.lifetime - (-b.birthTime);
      var connLife = Math.min(aRemaining, bRemaining);
      if (connLife < 2) continue;

      connections.push({ idA: a.id, idB: b.id, birthTime: stagger, lifetime: connLife });
      spawned++;
    }
  }

  // --- Render loop ---

  var startTime = performance.now();

  function render() {
    var now = performance.now();
    var elapsed = (now - startTime) / 1000;

    if (w === 0 || h === 0) {
      resize();
      requestAnimationFrame(render);
      return;
    }

    // Smooth color transition
    var targetColor = getTargetColor(canvasRiskScore);
    lerpRGB(currentColor, targetColor, 0.025);
    var cr = currentColor[0] | 0;
    var cg = currentColor[1] | 0;
    var cb = currentColor[2] | 0;

    // Spawn nodes
    if (!prefersReducedMotion && elapsed - lastNodeSpawn > NODE_SPAWN_INTERVAL) {
      spawnNode(elapsed);
      lastNodeSpawn = elapsed;
    }

    // Spawn connections
    if (!prefersReducedMotion && elapsed - lastConnSpawn > CONN_SPAWN_INTERVAL) {
      trySpawnConnection(elapsed);
      lastConnSpawn = elapsed;
    }

    // Remove dead nodes
    for (var i = nodes.length - 1; i >= 0; i--) {
      var age = elapsed - nodes[i].birthTime;
      if (age > nodes[i].lifetime) removeNode(i);
    }

    // Remove dead / orphaned connections
    for (var ci = connections.length - 1; ci >= 0; ci--) {
      var c = connections[ci];
      var cAge = elapsed - c.birthTime;
      if (cAge > c.lifetime || !nodeMap[c.idA] || !nodeMap[c.idB]) {
        connections.splice(ci, 1);
      }
    }

    // Clear
    ctx.fillStyle = "#0a0a0b";
    ctx.fillRect(0, 0, w, h);

    // *** Draw stars first (behind network) ***
    drawStars(elapsed);

    // Precompute node positions + opacities
    var posMap = {};
    for (var ni = 0; ni < nodes.length; ni++) {
      var n = nodes[ni];
      var nAge = elapsed - n.birthTime;
      var op = lifecycleOpacity(nAge, n.lifetime);
      if (op <= 0) continue;
      var pos = nodePos(n, elapsed);
      posMap[n.id] = { px: pos[0], py: pos[1], opacity: op, r: n.radius };
    }

    // Draw connections
    ctx.lineWidth = LINE_WIDTH;
    var diag = Math.sqrt(w * w + h * h);
    var refPx = DIST_REF * diag;

    for (var li = 0; li < connections.length; li++) {
      var conn = connections[li];
      var pa = posMap[conn.idA];
      var pb = posMap[conn.idB];
      if (!pa || !pb) continue;

      var connAge = elapsed - conn.birthTime;
      var fadeIn = clamp(connAge / CONN_FADE_IN, 0, 1);
      var nodeGate = Math.min(pa.opacity, pb.opacity);
      var connOp = Math.min(fadeIn, nodeGate);
      if (connOp <= 0) continue;

      var ldx = pa.px - pb.px;
      var ldy = pa.py - pb.py;
      var ldist = Math.sqrt(ldx * ldx + ldy * ldy);
      var distFade = Math.exp(-ldist / refPx);
      var lineAlpha = distFade * connOp * MAX_LINE_ALPHA;
      if (lineAlpha < 0.003) continue;

      ctx.strokeStyle = "rgba(" + cr + ", " + cg + ", " + cb + ", " + lineAlpha.toFixed(3) + ")";
      ctx.beginPath();
      ctx.moveTo(pa.px, pa.py);
      ctx.lineTo(pb.px, pb.py);
      ctx.stroke();
    }

    // Draw nodes
    var ids = Object.keys(posMap);
    for (var di = 0; di < ids.length; di++) {
      var p = posMap[ids[di]];

      // Glow
      var glowAlpha = p.opacity * MAX_GLOW_ALPHA;
      if (glowAlpha > 0.003) {
        var gradient = ctx.createRadialGradient(p.px, p.py, 0, p.px, p.py, p.r * 4);
        gradient.addColorStop(0, "rgba(" + cr + ", " + cg + ", " + cb + ", " + glowAlpha.toFixed(3) + ")");
        gradient.addColorStop(1, "rgba(" + cr + ", " + cg + ", " + cb + ", 0)");
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(p.px, p.py, p.r * 4, 0, Math.PI * 2);
        ctx.fill();
      }

      // Core dot
      var dotAlpha = p.opacity * MAX_NODE_ALPHA;
      ctx.fillStyle = "rgba(" + cr + ", " + cg + ", " + cb + ", " + dotAlpha.toFixed(3) + ")";
      ctx.beginPath();
      ctx.arc(p.px, p.py, p.r, 0, Math.PI * 2);
      ctx.fill();
    }

    requestAnimationFrame(render);
  }

  // --- Init ---
  resize();
  window.addEventListener("resize", resize);
  generateStars();
  seedNodes();
  seedConnections();
  requestAnimationFrame(render);

})();
