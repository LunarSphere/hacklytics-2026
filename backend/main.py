"""
Hacklytics 2026 — Backend API
==============================

Endpoints
---------
GET /health
    Liveness check.

GET /stocks?tickers=NVDA,AAPL,DE
    Runs the pipeline for multiple tickers in one call. Returns a list
    of results plus a summary of any tickers that failed.

GET /stocks/{ticker}
    Runs the full SEC → metrics → Databricks pipeline for a single ticker.
    Always re-computes (no cache).

GET /report?tickers=AAPL,TSLA
    Generates a formal LangChain / Gemini financial analysis report for one
    or more comma-separated tickers.

Deploy locally + expose via ngrok
----------------------------------
    uvicorn main:app --host 0.0.0.0 --port 5000 --reload
    ngrok http 5000          # copy the https:// URL → frontend .env
    # FastAPI interactive docs available at http://localhost:5000/docs
"""

import traceback
from typing import Any, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import quant_tool
import stock_health

load_dotenv()  # for Databricks credentials, but doesn't affect the rest of the server if .env is missing

# langchainWorkflow is imported lazily inside get_report() so a missing
# optional dep (e.g. python-dotenv, langchain_google_genai) doesn't prevent
# the server from starting.

# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Hacklytics 2026 — Fraud Risk API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class StockResponse(BaseModel):
    ticker: str
    company_name: Optional[str]
    # --- Fraud / accounting risk (from SEC + quant_metrics) ---
    m_score: float
    z_score: float
    accruals_ratio: float
    short_interest: Any          # nested dict from quant_metrics
    insider_trading: Any         # nested dict from quant_metrics
    composite_fraud_risk_score: float
    # --- Performance / market risk (from yfinance via stock_health) ---
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    var_95: Optional[float] = None
    cvar_95: Optional[float] = None
    max_drawdown: Optional[float] = None
    volatility: Optional[float] = None
    composite_stock_health_score: Optional[float] = None


class StockError(BaseModel):
    ticker: str
    error: str


class MultiStockResponse(BaseModel):
    results: List[StockResponse]
    errors: List[StockError]   # tickers that failed, with the reason


class ReportResponse(BaseModel):
    tickers: List[str]
    report_markdown: str
    summary: Optional[str] = None


class HealthResponse(BaseModel):
    status: str


class StockHealthResponse(BaseModel):
    ticker: str
    sharpe: float
    sortino: float
    alpha: float
    beta: float
    var_95: float
    cvar_95: float
    max_drawdown: float
    volatility: float
    composite_stock_health_score: float


class CreateUserRequest(BaseModel):
    phone: str
    name: str


class UserPortfolioRequest(BaseModel):
    tickers: List[str]


class PortfolioEntry(BaseModel):
    ticker: str
    composite_fraud_risk_score: Optional[float]
    composite_stock_health_score: Optional[float]
    last_updated: Optional[str]


class UserResponse(BaseModel):
    phone: str
    name: str
    portfolio: List[PortfolioEntry]
    avg_fraud_score: Optional[float]
    avg_health_score: Optional[float]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["Meta"])
def health():
    """Liveness check."""
    return HealthResponse(status="ok")


@app.get(
    "/stocks",
    response_model=MultiStockResponse,
    tags=["Quant"],
    summary="Run the pipeline for multiple tickers in one call",
)
def get_stocks(
    tickers: str = Query(
        ...,
        description="Comma-separated ticker symbols, e.g. `NVDA,AAPL,DE`",
        examples=["NVDA,AAPL,DE"],
    )
):
    """
    Runs SEC fetch → metrics calculation → Databricks upsert for each ticker
    in the comma-separated **tickers** query param.

    Tickers that fail (not found, pipeline error) are collected in the
    `errors` list so one bad ticker never blocks the rest.

    - **tickers**: comma-separated ticker symbols, e.g. `NVDA,AAPL,DE`
    """
    ticker_list: List[str] = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="No valid tickers provided.")

    results: List[StockResponse] = []
    errors: List[StockError] = []

    for ticker in ticker_list:
        try:
            resolved_ticker, company_name, res = quant_tool.run_pipeline(ticker)
            h: dict = {}
            try:
                h = stock_health.compute_health(resolved_ticker)
                quant_tool.upsert_health_to_databricks_safe(resolved_ticker, h)
            except Exception:
                traceback.print_exc()
            results.append(StockResponse(
                ticker=resolved_ticker,
                company_name=company_name,
                m_score=res["m_score"],
                z_score=res["z_score"],
                accruals_ratio=res["accruals_ratio"],
                short_interest=res.get("short_interest"),
                insider_trading=res.get("insider_trading"),
                composite_fraud_risk_score=res["composite_fraud_risk_score"],
                sharpe=h.get("sharpe"),
                sortino=h.get("sortino"),
                alpha=h.get("alpha"),
                beta=h.get("beta"),
                var_95=h.get("var_95"),
                cvar_95=h.get("cvar_95"),
                max_drawdown=h.get("max_drawdown"),
                volatility=h.get("volatility"),
                composite_stock_health_score=h.get("composite_stock_health_score"),
            ))
        except SystemExit:
            errors.append(StockError(ticker=ticker, error="Ticker not found."))
        except Exception as exc:
            traceback.print_exc()
            errors.append(StockError(ticker=ticker, error=str(exc)))

    if not results and errors:
        # Every ticker failed — return 422 so the frontend can surface the errors
        raise HTTPException(
            status_code=422,
            detail=[e.dict() for e in errors],
        )

    return MultiStockResponse(results=results, errors=errors)


@app.get(
    "/stocks/{ticker}",
    response_model=StockResponse,
    tags=["Quant"],
    summary="Run the full pipeline for a single ticker",
)
def get_stock(ticker: str):
    """
    Runs SEC fetch → metrics calculation → Databricks upsert for **ticker**
    and returns all computed fraud-risk metrics.

    - **ticker**: stock ticker symbol, e.g. `AAPL`
    """
    ticker = ticker.upper()
    try:
        resolved_ticker, company_name, results = quant_tool.run_pipeline(ticker)
    except SystemExit:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Pipeline failed — check server logs.")

    # Compute health metrics — non-fatal if yfinance/network fails
    health: dict = {}
    try:
        health = stock_health.compute_health(resolved_ticker)
        quant_tool.upsert_health_to_databricks_safe(resolved_ticker, health)
    except Exception:
        traceback.print_exc()

    return StockResponse(
        ticker=resolved_ticker,
        company_name=company_name,
        m_score=results["m_score"],
        z_score=results["z_score"],
        accruals_ratio=results["accruals_ratio"],
        short_interest=results.get("short_interest"),
        insider_trading=results.get("insider_trading"),
        composite_fraud_risk_score=results["composite_fraud_risk_score"],
        sharpe=health.get("sharpe"),
        sortino=health.get("sortino"),
        alpha=health.get("alpha"),
        beta=health.get("beta"),
        var_95=health.get("var_95"),
        cvar_95=health.get("cvar_95"),
        max_drawdown=health.get("max_drawdown"),
        volatility=health.get("volatility"),
        composite_stock_health_score=health.get("composite_stock_health_score"),
    )


@app.get(
    "/report",
    response_model=ReportResponse,
    tags=["Report"],
    summary="Generate a LangChain / Gemini report for one or more tickers",
)
def get_report(
    tickers: str = Query(
        ...,
        description="Comma-separated ticker symbols, e.g. `AAPL` or `AAPL,TSLA,NVDA`",
        examples=["AAPL", "AAPL,TSLA"],
    )
):
    """
    Calls the LangChain multi-agent workflow to produce a formal markdown
    report covering news sentiment and quantitative risk metrics.

    - **tickers**: one or more comma-separated ticker symbols
    """
    ticker_list: List[str] = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="No valid tickers provided.")

    try:
        import langchainWorkflow
        report_md = langchainWorkflow.generate_report(ticker_list)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Report generation failed — check server logs.")

    report_text = report_md.get("report", "") if isinstance(report_md, dict) else str(report_md)
    summary_text = report_md.get("summary") if isinstance(report_md, dict) else None
    return ReportResponse(tickers=ticker_list, report_markdown=report_text, summary=summary_text)


# ---------------------------------------------------------------------------
# Health Score
# ---------------------------------------------------------------------------

@app.get(
    "/health-score/{ticker}",
    response_model=StockHealthResponse,
    tags=["Health"],
    summary="Compute performance & risk metrics for a single ticker",
)
def get_health_score(ticker: str):
    """
    Downloads 1 year of daily prices via yfinance (free) and computes:
    Sharpe, Sortino, Alpha, Beta, VaR 95%, CVaR 95%, Max Drawdown, Volatility,
    and a weighted **composite_stock_health_score** (0–100).

    Results are upserted to the **stock_health** Databricks table.
    """
    ticker = ticker.upper()
    try:
        health = stock_health.compute_health(ticker)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Health score computation failed — check server logs.")

    try:
        conn   = quant_tool.get_connection()
        cursor = conn.cursor()
        try:
            quant_tool.ensure_health_table(cursor)
            quant_tool.upsert_health_to_databricks(cursor, ticker, health)
        finally:
            cursor.close()
            conn.close()
    except Exception:
        traceback.print_exc()  # non-fatal — return metrics even if DB write fails

    return StockHealthResponse(**health)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@app.post(
    "/users",
    status_code=201,
    tags=["Users"],
    summary="Register a new user",
)
def create_user(body: CreateUserRequest):
    """
    Creates a user record keyed by **phone number**.
    If the phone already exists the record is left unchanged (idempotent).
    """
    try:
        conn   = quant_tool.get_connection()
        cursor = conn.cursor()
        try:
            quant_tool.ensure_users_table(cursor)
            quant_tool.upsert_user(cursor, body.phone, body.name)
        finally:
            cursor.close()
            conn.close()
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to register user.")

    return {"phone": body.phone, "name": body.name}


@app.post(
    "/users/{phone}/portfolio",
    status_code=201,
    tags=["Users"],
    summary="Add tickers to a user's portfolio",
)
def add_to_portfolio(phone: str, body: UserPortfolioRequest):
    """
    Adds one or more tickers to the user's portfolio.
    Duplicate entries are silently ignored (idempotent per ticker).

    - **phone**: user's phone number
    - **body.tickers**: list of ticker symbols, e.g. `["AAPL", "NVDA"]`
    """
    if not body.tickers:
        raise HTTPException(status_code=400, detail="tickers list must not be empty.")

    tickers = [t.strip().upper() for t in body.tickers if t.strip()]

    try:
        conn   = quant_tool.get_connection()
        cursor = conn.cursor()
        try:
            quant_tool.ensure_users_table(cursor)
            quant_tool.ensure_portfolio_table(cursor)
            user = quant_tool.read_user(cursor, phone)
            if not user:
                raise HTTPException(status_code=404, detail=f"User '{phone}' not found.")
            quant_tool.add_to_portfolio(cursor, phone, tickers)
        finally:
            cursor.close()
            conn.close()
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to update portfolio.")

    return {"phone": phone, "tickers_added": tickers}


@app.get(
    "/users/{phone}",
    response_model=UserResponse,
    tags=["Users"],
    summary="Get a user with their portfolio and average scores",
)
def get_user(phone: str):
    """
    Returns the user record and every ticker in their portfolio.
    Each entry includes the latest **composite_fraud_risk_score** and
    **composite_stock_health_score** from Databricks (null if the ticker
    hasn't been analysed yet).

    **avg_fraud_score** and **avg_health_score** are computed live,
    excluding tickers with no data yet.
    """
    try:
        conn   = quant_tool.get_connection()
        cursor = conn.cursor()
        try:
            quant_tool.ensure_users_table(cursor)
            quant_tool.ensure_portfolio_table(cursor)
            quant_tool.ensure_health_table(cursor)
            user = quant_tool.read_user(cursor, phone)
            if not user:
                raise HTTPException(status_code=404, detail=f"User '{phone}' not found.")
            portfolio = quant_tool.read_portfolio(cursor, phone)
        finally:
            cursor.close()
            conn.close()
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch user data.")

    fraud_scores  = [e["composite_fraud_risk_score"]   for e in portfolio if e["composite_fraud_risk_score"]   is not None]
    health_scores = [e["composite_stock_health_score"] for e in portfolio if e["composite_stock_health_score"] is not None]

    return UserResponse(
        phone=user["phone"],
        name=user["name"],
        portfolio=[PortfolioEntry(**e) for e in portfolio],
        avg_fraud_score=round(sum(fraud_scores)   / len(fraud_scores),  2) if fraud_scores  else None,
        avg_health_score=round(sum(health_scores) / len(health_scores), 2) if health_scores else None,
    )


# ---------------------------------------------------------------------------
# Entry-point (uvicorn main:app --reload  OR  python main.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
