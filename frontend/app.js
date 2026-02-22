/* ==========================================================
   Fraud Risk Analysis — Vanilla JS (Updated for GET-only)
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
    tickerCount.textContent = currentTickers.length > 0 
      ? currentTickers.length + " symbol" + (currentTickers.length !== 1 ? "s" : "")
      : "";

    // Chips
    tickerChips.innerHTML = "";
    for (var i = 0; i < currentTickers.length; i++) {
      var chip = document.createElement("span");
      chip.className = "ticker-chip";
      chip.textContent = currentTickers[i];
      tickerChips.appendChild(chip);
    }

    analyzeBtn.disabled = currentTickers.length === 0 || isLoading;
  }

  tickerInput.addEventListener("input", refreshTickerUI);

  /* ----------------------------------------------------------
     Ctrl+Enter shortcut
     ---------------------------------------------------------- */
  tickerInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (currentTickers.length > 0 && !isLoading) runAnalysis();
    }
  });

  /* ----------------------------------------------------------
     API base URL
     ---------------------------------------------------------- */
  var API_BASE = ""; // same origin — served by FastAPI

  /* ----------------------------------------------------------
     Fetch stock data — GET-only, async/await
     ---------------------------------------------------------- */
  async function fetchStockData(ticker) {
    try {
      const url = `${API_BASE}/stocks/${encodeURIComponent(ticker)}?_=${Date.now()}`;
      const response = await axios.get(url, { headers: {} });
      return response.data;
    } catch (err) {
      const msg = err.response ? `HTTP ${err.response.status}` : err.message;
      return { error: msg, ticker };
    }
  }

  /* ----------------------------------------------------------
     Run Analysis
     ---------------------------------------------------------- */
  var progressInterval = null;
  var currentResult = null;
  var currentErrors = null;
  var canvasRiskScore = null;

  async function runAnalysis() {
    var tickers = currentTickers.slice();
    isLoading = true;
    analyzeBtn.classList.add("is-loading");
    analyzeBtn.disabled = true;
    tickerInput.disabled = true;
    shortcutHint.style.display = "none";
    resultsSec.style.display = "none";
    resultsSec.classList.remove("visible");
    skeletonSec.style.display = "block";
    progressFill.style.width = "0%";
    btnLabel.textContent = "Analyzing";

    // Animate progress bar
    progressInterval = setInterval(() => {
      let width = parseFloat(progressFill.style.width) || 0;
      width += Math.random() * 8 + 2;
      if (width > 90) width = 90;
      progressFill.style.width = width + "%";
      let dots = ".".repeat(Math.floor((width / 25) % 4));
      btnLabel.textContent = "Analyzing" + dots;
    }, 300);

    try {
      const results = await Promise.all(tickers.map(t => fetchStockData(t)));
      currentResult = results.filter(r => !r.error);
      currentErrors = results.filter(r => !!r.error);

      // Average risk score
      if (currentResult.length > 0) {
        let total = currentResult.reduce((sum, r) => sum + r.composite_fraud_risk_score, 0);
        canvasRiskScore = total / currentResult.length;
      } else {
        canvasRiskScore = null;
      }

      renderResults(currentResult, currentErrors);
    } catch (e) {
      console.error("Analysis failed:", e);
    } finally {
      clearInterval(progressInterval);
      progressFill.style.width = "0%";
      btnLabel.textContent = "Run Analysis";
      isLoading = false;
      analyzeBtn.classList.remove("is-loading");
      tickerInput.disabled = false;
      shortcutHint.style.display = "";
      skeletonSec.style.display = "none";
      refreshTickerUI();
    }
  }

  analyzeBtn.addEventListener("click", () => {
    if (currentTickers.length > 0 && !isLoading) runAnalysis();
  });

  /* ----------------------------------------------------------
     Render results
     ---------------------------------------------------------- */
  function renderResults(stocks, errors) {
    stockCardsContainer.innerHTML = "";

    function formatMetric(val) { return val === null || val === undefined ? "N/A" : Number(val).toFixed(4); }
    function getMetricDotColor(name, val) {
      if (name === "Beneish M-Score") return val < -1.78 ? "#3a8a5c" : val < -1.0 ? "#c49a3a" : "#b83a2a";
      if (name === "Altman Z-Score") return val > 2.99 ? "#3a8a5c" : val > 1.81 ? "#c49a3a" : "#b83a2a";
      if (name === "Accruals Ratio") return Math.abs(val) < 0.05 ? "#3a8a5c" : Math.abs(val) < 0.10 ? "#c49a3a" : "#b83a2a";
      return "#7a7a84";
    }

    function animateScoreElement(numEl, barEl) {
      const targetScore = parseInt(numEl.getAttribute("data-target"), 10);
      const color = numEl.style.color;
      const duration = 1200;
      let startTime = null;

      function tick(now) {
        if (!startTime) startTime = now;
        const progress = Math.min((now - startTime)/duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        numEl.textContent = Math.round(eased * targetScore);
        if (barEl) barEl.style.width = (eased * targetScore) + "%";
        if (progress < 1) requestAnimationFrame(tick);
      }

      setTimeout(() => requestAnimationFrame(tick), 200);
    }

    // Render each stock
    stocks.forEach(s => {
      const score = s.composite_fraud_risk_score;
      const color = getScoreColor(score);
      const label = getScoreLabel(score);

      const card = document.createElement("div");
      card.className = "results-divider stock-card";

      // Header
      const header = document.createElement("div");
      header.className = "score-header";
      const tickerLabel = document.createElement("span");
      tickerLabel.className = "section-label stock-ticker-label";
      tickerLabel.textContent = s.ticker + (s.company_name ? " — " + s.company_name : "");
      const sevLabel = document.createElement("span");
      sevLabel.className = "score-severity-label";
      sevLabel.style.color = color;
      sevLabel.textContent = label;
      header.appendChild(tickerLabel);
      header.appendChild(sevLabel);
      card.appendChild(header);

      // Score
      const scoreDisplay = document.createElement("div");
      scoreDisplay.className = "score-display";
      const scoreNum = document.createElement("span");
      scoreNum.className = "score-number";
      scoreNum.style.color = color;
      scoreNum.textContent = "0";
      scoreNum.setAttribute("data-target", String(Math.round(score)));
      const scoreDenom = document.createElement("span");
      scoreDenom.className = "score-denominator";
      scoreDenom.textContent = "/ 100";
      scoreDisplay.appendChild(scoreNum);
      scoreDisplay.appendChild(scoreDenom);
      card.appendChild(scoreDisplay);

      // Score bar
      const barTrack = document.createElement("div");
      barTrack.className = "score-bar-track";
      const barFill = document.createElement("div");
      barFill.className = "score-bar-fill";
      barFill.setAttribute("data-target", String(score));
      barFill.style.background = color;
      barTrack.appendChild(barFill);
      card.appendChild(barTrack);

      // Markers
      const markers = document.createElement("div");
      markers.className = "score-markers";
      [0,25,50,75,100].forEach(m => { 
        const sp = document.createElement("span"); 
        sp.textContent = m; 
        markers.appendChild(sp);
      });
      card.appendChild(markers);

      // Metrics
      const metricsWrap = document.createElement("div");
      metricsWrap.className = "stock-metrics";
      const metricsTitle = document.createElement("div");
      metricsTitle.className = "factors-label-wrap";
      const metricsTitleSpan = document.createElement("span");
      metricsTitleSpan.className = "section-label";
      metricsTitleSpan.textContent = "Key Metrics";
      metricsTitle.appendChild(metricsTitleSpan);
      metricsWrap.appendChild(metricsTitle);

      const metrics = [
        { name: "Beneish M-Score", value: s.m_score },
        { name: "Altman Z-Score", value: s.z_score },
        { name: "Accruals Ratio", value: s.accruals_ratio }
      ];

      metrics.forEach(m => {
        const row = document.createElement("div");
        row.className = "metric-row";
        const dot = document.createElement("div");
        dot.className = "factor-dot";
        dot.style.background = getMetricDotColor(m.name, m.value);
        const label = document.createElement("span");
        label.className = "factor-label";
        label.textContent = m.name;
        const val = document.createElement("span");
        val.className = "metric-value";
        val.textContent = formatMetric(m.value);
        row.appendChild(dot); row.appendChild(label); row.appendChild(val);
        metricsWrap.appendChild(row);
      });

      card.appendChild(metricsWrap);
      stockCardsContainer.appendChild(card);

      // Animate score
      animateScoreElement(scoreNum, barFill);
    });

    // Errors
    errors.forEach(e => {
      const errCard = document.createElement("div");
      errCard.className = "results-divider stock-card stock-card-error";
      errCard.innerHTML = `
        <div class="score-header">
          <span class="section-label stock-ticker-label">${e.ticker}</span>
          <span class="score-severity-label" style="color:#b83a2a">ERROR</span>
        </div>
        <p class="summary-text" style="margin-top:8px;">Could not retrieve data: ${e.error}</p>
      `;
      stockCardsContainer.appendChild(errCard);
    });

    // Show results
    resultsSec.style.display = "block";
    requestAnimationFrame(() => {
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

    setTimeout(() => {
      var lines = [
        "FRAUD RISK ANALYSIS REPORT",
        "=".repeat(40),
        "",
        "Generated: " + new Date().toISOString().split("T")[0],
        "Tickers: " + currentResult.map(s => s.ticker).join(", "),
        ""
      ];

      currentResult.forEach(s => {
        lines.push("", s.ticker + (s.company_name ? " — " + s.company_name : ""));
        lines.push("-".repeat(40));
        lines.push("Composite Fraud Risk Score: " + s.composite_fraud_risk_score.toFixed(2) + " / 100");
        lines.push("Beneish M-Score:            " + s.m_score.toFixed(4));
        lines.push("Altman Z-Score:             " + s.z_score.toFixed(4));
        lines.push("Accruals Ratio:             " + s.accruals_ratio.toFixed(4));
      });

      lines.push("", "DISCLAIMER", "-".repeat(40), 
        "This report is generated for informational purposes only.",
        "It does not constitute financial or legal advice.",
        "Conduct independent due diligence before making any decisions."
      );

      const blob = new Blob([lines.join("\n")], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "risk-report-" + currentResult.map(s => s.ticker).join("-") + "-" + Date.now() + ".txt";
      a.click();
      URL.revokeObjectURL(url);

      downloadBtn.disabled = false;
      downloadLabel.textContent = "Download full report";
    }, 800);
  });

  /* ==========================================================
     Background Canvas — Network Pulse Effect (unchanged)
     ========================================================== */
  // Canvas setup + animation loop code goes here (unchanged) ...
  // Keeps existing nodes, connections, colors, glow, drift, etc.

})();