"""
stock_health.py — Performance & risk metrics via yfinance
==========================================================
Mirrors the pattern of quant_metrics.py for fraud scores.

Formulas ported from the ALPHA hackathon winner (Sergio799/ALPHA)
  src/quant/core/risk-metrics.ts

Public API
----------
compute_health(ticker: str) -> dict
    Downloads 1 year of daily prices (free yfinance), computes all health
    metrics, and returns a flat dict ready for Databricks upsert + API response.
"""

import os

import numpy as np
import yfinance as yf

BACKEND_DIR  = os.path.dirname(os.path.abspath(__file__))
TRADING_DAYS = 252
BENCHMARK    = "^GSPC"   # S&P 500
RF_TICKER    = "^TNX"    # 10-year Treasury yield (annualised %)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _fetch_prices(ticker: str):
    """Download 1 year of adjusted close prices for ticker + benchmark in one call."""
    raw = yf.download(
        [ticker, BENCHMARK], period="1y", auto_adjust=True, progress=False
    )
    if raw is None or raw.empty:
        raise ValueError(f"No price data returned for {ticker} or {BENCHMARK}.")
    data = raw["Close"]

    stock_prices  = data[ticker].dropna().values.astype(float)
    market_prices = data[BENCHMARK].dropna().values.astype(float)

    # Align lengths (they may differ by a day or two on holidays)
    min_len       = min(len(stock_prices), len(market_prices))
    stock_prices  = stock_prices[-min_len:]
    market_prices = market_prices[-min_len:]

    # Risk-free rate: try live ^TNX, fall back to 4 %
    try:
        rf_raw = yf.download(RF_TICKER, period="5d", auto_adjust=True, progress=False)
        if rf_raw is None or rf_raw.empty:
            raise ValueError("No data returned for RF_TICKER")
        rf_series  = rf_raw["Close"].dropna()
        rf_annual  = float(rf_series.iloc[-1]) / 100
    except Exception:
        rf_annual = 0.04

    return stock_prices, market_prices, rf_annual


def _daily_returns(prices: np.ndarray) -> np.ndarray:
    return np.diff(prices) / prices[:-1]


# ---------------------------------------------------------------------------
# Individual metric functions  (ported from ALPHA risk-metrics.ts)
# ---------------------------------------------------------------------------

def _sharpe(returns: np.ndarray, rf_annual: float) -> float:
    """Annualised Sharpe Ratio."""
    rf_daily = rf_annual / TRADING_DAYS
    excess   = returns - rf_daily
    std      = returns.std()
    if std == 0:
        return 0.0
    return float((excess.mean() / std) * np.sqrt(TRADING_DAYS))


def _sortino(returns: np.ndarray, rf_annual: float) -> float:
    """Annualised Sortino Ratio (penalises downside volatility only)."""
    rf_daily     = rf_annual / TRADING_DAYS
    excess       = returns - rf_daily
    downside     = returns[returns < 0]
    if len(downside) == 0:
        return 999.0            # no negative days — cap at large positive
    downside_std = np.sqrt(np.mean(downside ** 2))
    if downside_std == 0:
        return 0.0
    return float((excess.mean() / downside_std) * np.sqrt(TRADING_DAYS))


def _beta(stock_returns: np.ndarray, market_returns: np.ndarray) -> float:
    """Beta vs S&P 500."""
    market_var = market_returns.var()
    if market_var == 0:
        return 0.0
    cov = np.cov(stock_returns, market_returns)[0][1]
    return float(cov / market_var)


def _alpha(stock_prices: np.ndarray, market_prices: np.ndarray,
           beta: float, rf_annual: float) -> float:
    """Jensen's Alpha: actual total return − CAPM expected return."""
    stock_total  = (stock_prices[-1]  - stock_prices[0])  / stock_prices[0]
    market_total = (market_prices[-1] - market_prices[0]) / market_prices[0]
    expected     = rf_annual + beta * (market_total - rf_annual)
    return float(stock_total - expected)


def _var95(returns: np.ndarray) -> float:
    """95% VaR — maximum expected daily loss (positive decimal, e.g. 0.025 = 2.5%)."""
    return float(abs(np.percentile(returns, 5)))


def _cvar95(returns: np.ndarray) -> float:
    """95% CVaR (Expected Shortfall) — mean of the worst 5% days (positive decimal)."""
    cutoff = np.percentile(returns, 5)
    tail   = returns[returns <= cutoff]
    if len(tail) == 0:
        return 0.0
    return float(abs(tail.mean()))


def _max_drawdown(prices: np.ndarray) -> float:
    """Maximum peak-to-trough decline over the period, in [0, 1]."""
    peak     = np.maximum.accumulate(prices)
    drawdown = (peak - prices) / peak
    return float(drawdown.max())


def _volatility(returns: np.ndarray) -> float:
    """Annualised volatility (std of daily returns × √252)."""
    return float(returns.std() * np.sqrt(TRADING_DAYS))


# ---------------------------------------------------------------------------
# Composite health score
# ---------------------------------------------------------------------------

def _normalize_and_combine(sharpe: float, sortino: float,
                            alpha: float, max_drawdown: float) -> float:
    """
    Weights (validated against ALPHA hackathon winner insights-engine.ts):
        Sharpe       40 %  — risk-adjusted return (primary signal)
        Alpha        30 %  — outperformance vs S&P 500
        Max Drawdown 20 %  — inverted (lower drawdown = healthier)
        Sortino      10 %  — downside-only risk supplement

    Returns composite in [0, 1]; caller scales to 0–100.
    """
    # Sharpe: map [-1, 3] → [0, 1]
    norm_sharpe   = max(0.0, min(1.0, (sharpe + 1) / 4))

    # Sortino: cap at 5 so outliers don't dominate, map [-1, 5] → [0, 1]
    sort_capped   = min(sortino, 5.0)
    norm_sortino  = max(0.0, min(1.0, (sort_capped + 1) / 6))

    # Alpha: map [-0.3, +0.3] → [0, 1]
    norm_alpha    = max(0.0, min(1.0, (alpha + 0.3) / 0.6))

    # Max Drawdown: invert — lower drawdown = healthier stock
    norm_drawdown = max(0.0, min(1.0, 1.0 - max_drawdown))

    return (
        norm_sharpe   * 0.40 +
        norm_alpha    * 0.30 +
        norm_drawdown * 0.20 +
        norm_sortino  * 0.10
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_health(ticker: str) -> dict:
    """
    Compute all stock-health metrics for *ticker* using 1 year of daily prices.

    Returns
    -------
    {
        "ticker":                       str,
        "sharpe":                       float,   # annualised compare invest return vs risk
        "sortino":                      float,   # annualised version of Sharpe that penalises downside volatility only
        "alpha":                        float,   # vs S&P 500 (annual) measure of active return on investment — how much did it beat/fall short of CAPM expected return?
        "beta":                         float,   # vs S&P 500 measure of volatility/risk — how much does it move vs market?
        "var_95":                       float,   # daily positive decimal value at risk (max expected loss at 95% confidence)
        "cvar_95":                      float,   # daily positive decimal 
        "max_drawdown":                 float,   # peak-to-trough [0, 1]
        "volatility":                   float,   # annualised std of returns
        "composite_stock_health_score": float,   # 0–100
    }
    """
    ticker = ticker.upper()
    stock_prices, market_prices, rf_annual = _fetch_prices(ticker)

    stock_ret  = _daily_returns(stock_prices)
    market_ret = _daily_returns(market_prices)

    sharpe   = _sharpe(stock_ret, rf_annual)
    sortino  = _sortino(stock_ret, rf_annual)
    beta     = _beta(stock_ret, market_ret)
    alpha    = _alpha(stock_prices, market_prices, beta, rf_annual)
    var95    = _var95(stock_ret)
    cvar95   = _cvar95(stock_ret)
    max_dd   = _max_drawdown(stock_prices)
    vol      = _volatility(stock_ret)

    composite = _normalize_and_combine(sharpe, sortino, alpha, max_dd)

    return {
        "ticker":                       ticker,
        "sharpe":                       round(sharpe,     4),
        "sortino":                      round(sortino,    4),
        "alpha":                        round(alpha,      4),
        "beta":                         round(beta,       4),
        "var_95":                       round(var95,      4),
        "cvar_95":                      round(cvar95,     4),
        "max_drawdown":                 round(max_dd,     4),
        "volatility":                   round(vol,        4),
        "composite_stock_health_score": round(composite * 100, 2),
    }
