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

  /* ----------------------------------------------------------
     Severity color map
     ---------------------------------------------------------- */
  var SEVERITY_COLORS = {
    low:      "#3a8a5c",
    moderate: "#8a8a3a",
    elevated: "#c49a3a",
    high:     "#b83a2a"
  };

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

    // Button
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
  var API_BASE = "https://unsupernaturally-riley-marc.ngrok-free.dev";

  /* ----------------------------------------------------------
     Fetch stock data from backend
     ---------------------------------------------------------- */
  // Ensure fetchStockData returns the fetch promise
  function fetchStockData(ticker) {
    const url = `${API_BASE}/stocks/${ticker}?timestamp=${new Date().getTime()}`; // Cache-busting query parameter

    return fetch(url, {
        method: 'GET',
        headers: {
            'Cache-Control': 'no-cache', // Prevent caching
        },
    })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('Fetched data:', data);
            return data; // Ensure data is returned to the caller
        })
        .catch(error => {
            console.error('Error fetching stock data:', error);
            throw error; // Re-throw the error to propagate it to the caller
        });
  }

  /* ----------------------------------------------------------
     Run Analysis
     ---------------------------------------------------------- */
  var progressInterval = null;
  var currentResult = null;
  var currentErrors = null;

  function runAnalysis() {
    var tickers = currentTickers.slice();
    isLoading = true;
    analyzeBtn.classList.add("is-loading");
    analyzeBtn.disabled = true;
    tickerInput.disabled = true;
    shortcutHint.style.display = "none";
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

    fetchStockData(tickers).then(function (results) {
      clearInterval(progressInterval);
      progressFill.style.width = "100%";
      btnLabel.textContent = "Analyzing...";

      setTimeout(function () {
        currentResult = results.filter(function (r) { return !r.error; });
        currentErrors = results.filter(function (r) { return !!r.error; });
        isLoading = false;
        analyzeBtn.classList.remove("is-loading");
        progressFill.style.width = "0%";
        btnLabel.textContent = "Run Analysis";
        tickerInput.disabled = false;
        shortcutHint.style.display = "";
        skeletonSec.style.display = "none";
        refreshTickerUI();

        // Use the average composite score for the canvas color
        if (currentResult.length > 0) {
          var totalScore = 0;
          for (var i = 0; i < currentResult.length; i++) {
            totalScore += currentResult[i].composite_fraud_risk_score;
          }
          canvasRiskScore = totalScore / currentResult.length;
        } else {
          canvasRiskScore = null;
        }

        renderResults(currentResult, currentErrors);
      }, 300);
    });
  }

  analyzeBtn.addEventListener("click", function () {
    if (currentTickers.length > 0 && !isLoading) runAnalysis();
  });

  /* ----------------------------------------------------------
     Render results — per-stock cards
     ---------------------------------------------------------- */
  function renderResults(stocks, errors) {
    stockCardsContainer.innerHTML = "";

    for (var i = 0; i < stocks.length; i++) {
      var s = stocks[i];
      var score = s.composite_fraud_risk_score;
      var color = getScoreColor(score);
      var label = getScoreLabel(score);

      // Card wrapper
      var card = document.createElement("div");
      card.className = "results-divider stock-card";

      // Header row: ticker + severity
      var header = document.createElement("div");
      header.className = "score-header";

      var tickerLabel = document.createElement("span");
      tickerLabel.className = "section-label stock-ticker-label";
      tickerLabel.textContent = s.ticker + (s.company_name ? " — " + s.company_name : "");

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

      // Metrics section
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
        { name: "Beneish M-Score",  value: s.m_score,        desc: "< -1.78 suggests no manipulation" },
        { name: "Altman Z-Score",   value: s.z_score,        desc: "> 2.99 suggests financial health" },
        { name: "Accruals Ratio",   value: s.accruals_ratio, desc: "Closer to 0 is generally better" }
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
      stockCardsContainer.appendChild(card);
    }

    // Show errors if any
    for (var e = 0; e < errors.length; e++) {
      var errCard = document.createElement("div");
      errCard.className = "results-divider stock-card stock-card-error";
      errCard.innerHTML =
        '<div class="score-header">' +
          '<span class="section-label stock-ticker-label">' + errors[e].ticker + '</span>' +
          '<span class="score-severity-label" style="color:#b83a2a">ERROR</span>' +
        '</div>' +
        '<p class="summary-text" style="margin-top:8px;">Could not retrieve data: ' + errors[e].error + '</p>';
      stockCardsContainer.appendChild(errCard);
    }

    // Show results with fade-in
    resultsSec.style.display = "block";
    requestAnimationFrame(function () {
      resultsSec.classList.add("visible");
      resultsSec.scrollIntoView({ behavior: "smooth", block: "start" });

      // Animate all score numbers + bars
      var scoreEls = stockCardsContainer.querySelectorAll(".score-number[data-target]");
      var barEls = stockCardsContainer.querySelectorAll(".score-bar-fill[data-target]");
      for (var k = 0; k < scoreEls.length; k++) {
        animateScoreElement(scoreEls[k], barEls[k]);
      }
    });
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
    var color = numEl.style.color;
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
      var lines = [
        "FRAUD RISK ANALYSIS REPORT",
        "=".repeat(40),
        "",
        "Generated: " + new Date().toISOString().split("T")[0],
        "Tickers: " + currentResult.map(function (s) { return s.ticker; }).join(", "),
        ""
      ];

      for (var i = 0; i < currentResult.length; i++) {
        var s = currentResult[i];
        lines.push("");
        lines.push(s.ticker + (s.company_name ? " — " + s.company_name : ""));
        lines.push("-".repeat(40));
        lines.push("Composite Fraud Risk Score: " + s.composite_fraud_risk_score.toFixed(2) + " / 100");
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

      var tickers = currentResult.map(function (s) { return s.ticker; });
      var blob = new Blob([lines.join("\n")], { type: "text/plain" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = "risk-report-" + tickers.join("-") + "-" + Date.now() + ".txt";
      a.click();
      URL.revokeObjectURL(url);

      downloadBtn.disabled = false;
      downloadLabel.textContent = "Download full report";
    }, 800);
  });

  /* ==========================================================
     Background Canvas — Network Pulse Effect
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
  seedNodes();
  seedConnections();
  requestAnimationFrame(render);

})();
