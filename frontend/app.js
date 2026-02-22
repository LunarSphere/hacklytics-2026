/* ==========================================================
   Fraud Risk Analysis â€” No fetch; data injected by FastAPI
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

  /* ----------------------------------------------------------
     Severity helpers
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
     Ticker UI
     ---------------------------------------------------------- */
  var currentTickers = [];
  var canvasRiskScore = null;

  function refreshTickerUI() {
    currentTickers = parseTickers(tickerInput.value);

    tickerCount.textContent = currentTickers.length > 0
      ? currentTickers.length + " symbol" + (currentTickers.length !== 1 ? "s" : "")
      : "";

    tickerChips.innerHTML = "";
    for (var i = 0; i < currentTickers.length; i++) {
      var chip = document.createElement("span");
      chip.className = "ticker-chip";
      chip.textContent = currentTickers[i];
      tickerChips.appendChild(chip);
    }

    analyzeBtn.disabled = currentTickers.length === 0;
  }

  tickerInput.addEventListener("input", refreshTickerUI);

  tickerInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (currentTickers.length > 0) runAnalysis();
    }
  });

  /* ----------------------------------------------------------
     Run Analysis â€” navigate to /?tickers=... (Python does the work)
     ---------------------------------------------------------- */
  function runAnalysis() {
    if (currentTickers.length === 0) return;

    btnLabel.textContent = "Loading\u2026";
    analyzeBtn.disabled = true;
    analyzeBtn.classList.add("is-loading");
    progressFill.style.width = "60%";
    shortcutHint.style.display = "none";

    window.location.href = "/?tickers=" + encodeURIComponent(currentTickers.join(","));
  }

  analyzeBtn.addEventListener("click", function () {
    runAnalysis();
  });

  /* ----------------------------------------------------------
     On page load â€” restore state from URL, render PAGE_DATA
     ---------------------------------------------------------- */
  (function init() {
    var params = new URLSearchParams(window.location.search);
    var tickersParam = params.get("tickers");

    if (tickersParam) {
      tickerInput.value = tickersParam;
      refreshTickerUI();
    }

    if (window.PAGE_DATA) {
      var data = window.PAGE_DATA;
      var results = data.results || [];
      var errors  = data.errors  || [];

      if (results.length > 0) {
        var total = 0;
        for (var i = 0; i < results.length; i++) total += results[i].composite_fraud_risk_score;
        canvasRiskScore = total / results.length;
      }

      skeletonSec.style.display = "none";
      renderResults(results, errors);
    }
  })();

  /* ----------------------------------------------------------
     Render results
     ---------------------------------------------------------- */
  var currentResult = null;
  var currentErrors = null;

  function renderResults(stocks, errors) {
    currentResult = stocks;
    currentErrors = errors;
    stockCardsContainer.innerHTML = "";

    function formatMetric(val) {
      return val === null || val === undefined ? "N/A" : Number(val).toFixed(4);
    }

    function getMetricDotColor(name, val) {
      if (val === null || val === undefined) return "#7a7a84";
      if (name === "Beneish M-Score") return val < -1.78 ? "#3a8a5c" : val < -1.0 ? "#c49a3a" : "#b83a2a";
      if (name === "Altman Z-Score")  return val > 2.99  ? "#3a8a5c" : val > 1.81  ? "#c49a3a" : "#b83a2a";
      if (name === "Accruals Ratio")  return Math.abs(val) < 0.05 ? "#3a8a5c" : Math.abs(val) < 0.10 ? "#c49a3a" : "#b83a2a";
      return "#7a7a84";
    }

    function animateScoreElement(numEl, barEl) {
      var targetScore = parseInt(numEl.getAttribute("data-target"), 10);
      var duration = 1200;
      var startTime = null;

      function tick(now) {
        if (!startTime) startTime = now;
        var progress = Math.min((now - startTime) / duration, 1);
        var eased = 1 - Math.pow(1 - progress, 3);
        numEl.textContent = Math.round(eased * targetScore);
        if (barEl) barEl.style.width = (eased * targetScore) + "%";
        if (progress < 1) requestAnimationFrame(tick);
      }

      setTimeout(function () { requestAnimationFrame(tick); }, 200);
    }

    stocks.forEach(function (s) {
      var score = s.composite_fraud_risk_score;
      var color = getScoreColor(score);
      var label = getScoreLabel(score);

      var card = document.createElement("div");
      card.className = "results-divider stock-card";

      var header = document.createElement("div");
      header.className = "score-header";
      var tickerLabel = document.createElement("span");
      tickerLabel.className = "section-label stock-ticker-label";
      tickerLabel.textContent = s.ticker + (s.company_name ? " \u2014 " + s.company_name : "");
      var sevLabel = document.createElement("span");
      sevLabel.className = "score-severity-label";
      sevLabel.style.color = color;
      sevLabel.textContent = label;
      header.appendChild(tickerLabel);
      header.appendChild(sevLabel);
      card.appendChild(header);

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

      var barTrack = document.createElement("div");
      barTrack.className = "score-bar-track";
      var barFill = document.createElement("div");
      barFill.className = "score-bar-fill";
      barFill.setAttribute("data-target", String(score));
      barFill.style.background = color;
      barTrack.appendChild(barFill);
      card.appendChild(barTrack);

      var markers = document.createElement("div");
      markers.className = "score-markers";
      [0, 25, 50, 75, 100].forEach(function (m) {
        var sp = document.createElement("span");
        sp.textContent = m;
        markers.appendChild(sp);
      });
      card.appendChild(markers);

      var metricsWrap = document.createElement("div");
      metricsWrap.className = "stock-metrics";
      var metricsTitle = document.createElement("div");
      metricsTitle.className = "factors-label-wrap";
      var metricsTitleSpan = document.createElement("span");
      metricsTitleSpan.className = "section-label";
      metricsTitleSpan.textContent = "Key Metrics";
      metricsTitle.appendChild(metricsTitleSpan);
      metricsWrap.appendChild(metricsTitle);

      [
        { name: "Beneish M-Score", value: s.m_score },
        { name: "Altman Z-Score",  value: s.z_score },
        { name: "Accruals Ratio",  value: s.accruals_ratio }
      ].forEach(function (m) {
        var row = document.createElement("div");
        row.className = "metric-row";
        var dot = document.createElement("div");
        dot.className = "factor-dot";
        dot.style.background = getMetricDotColor(m.name, m.value);
        var lbl = document.createElement("span");
        lbl.className = "factor-label";
        lbl.textContent = m.name;
        var val = document.createElement("span");
        val.className = "metric-value";
        val.textContent = formatMetric(m.value);
        row.appendChild(dot); row.appendChild(lbl); row.appendChild(val);
        metricsWrap.appendChild(row);
      });

      card.appendChild(metricsWrap);
      stockCardsContainer.appendChild(card);
      animateScoreElement(scoreNum, barFill);
    });

    errors.forEach(function (e) {
      var errCard = document.createElement("div");
      errCard.className = "results-divider stock-card stock-card-error";
      errCard.innerHTML =
        '<div class="score-header">' +
          '<span class="section-label stock-ticker-label">' + e.ticker + '</span>' +
          '<span class="score-severity-label" style="color:#b83a2a">ERROR</span>' +
        '</div>' +
        '<p class="summary-text" style="margin-top:8px;">Could not retrieve data: ' + e.error + '</p>';
      stockCardsContainer.appendChild(errCard);
    });

    resultsSec.style.display = "block";
    requestAnimationFrame(function () {
      resultsSec.classList.add("visible");
      resultsSec.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  /* ----------------------------------------------------------
     Download report
     ---------------------------------------------------------- */
  downloadBtn.addEventListener("click", function () {
    if (!currentResult || currentResult.length === 0) return;
    downloadBtn.disabled = true;
    downloadLabel.textContent = "Preparing report...";

    setTimeout(function () {
      var lines = [
        "FRAUD RISK ANALYSIS REPORT",
        "=".repeat(40), "",
        "Generated: " + new Date().toISOString().split("T")[0],
        "Tickers: " + currentResult.map(function (s) { return s.ticker; }).join(", "), ""
      ];

      currentResult.forEach(function (s) {
        var fmt = function (v) { return v !== null && v !== undefined ? Number(v).toFixed(4) : "N/A"; };
        lines.push("", s.ticker + (s.company_name ? " \u2014 " + s.company_name : ""));
        lines.push("-".repeat(40));
        lines.push("Composite Fraud Risk Score: " + Number(s.composite_fraud_risk_score).toFixed(2) + " / 100");
        lines.push("Beneish M-Score:            " + fmt(s.m_score));
        lines.push("Altman Z-Score:             " + fmt(s.z_score));
        lines.push("Accruals Ratio:             " + fmt(s.accruals_ratio));
      });

      lines.push("", "DISCLAIMER", "-".repeat(40),
        "This report is generated for informational purposes only.",
        "It does not constitute financial or legal advice.",
        "Conduct independent due diligence before making any decisions."
      );

      var blob = new Blob([lines.join("\n")], { type: "text/plain" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = "risk-report-" + currentResult.map(function (s) { return s.ticker; }).join("-") + "-" + Date.now() + ".txt";
      a.click();
      URL.revokeObjectURL(url);
      downloadBtn.disabled = false;
      downloadLabel.textContent = "Download full report";
    }, 800);
  });

  /* ==========================================================
     Background Canvas -- Network Pulse Effect (unchanged)
     ========================================================== */
  // Canvas setup + animation loop code goes here (unchanged) ...
  // Keeps existing nodes, connections, colors, glow, drift, etc.

})();
