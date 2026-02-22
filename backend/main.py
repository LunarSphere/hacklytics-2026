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

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import quant_tool

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
    m_score: float
    z_score: float
    accruals_ratio: float
    short_interest: Any          # nested dict from quant_metrics
    insider_trading: Any         # nested dict from quant_metrics
    composite_fraud_risk_score: float


class StockError(BaseModel):
    ticker: str
    error: str


class MultiStockResponse(BaseModel):
    results: List[StockResponse]
    errors: List[StockError]   # tickers that failed, with the reason


class ReportResponse(BaseModel):
    tickers: List[str]
    report_markdown: str


class HealthResponse(BaseModel):
    status: str


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
            results.append(StockResponse(
                ticker=resolved_ticker,
                company_name=company_name,
                m_score=res["m_score"],
                z_score=res["z_score"],
                accruals_ratio=res["accruals_ratio"],
                short_interest=res.get("short_interest"),
                insider_trading=res.get("insider_trading"),
                composite_fraud_risk_score=res["composite_fraud_risk_score"],
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

    return StockResponse(
        ticker=resolved_ticker,
        company_name=company_name,
        m_score=results["m_score"],
        z_score=results["z_score"],
        accruals_ratio=results["accruals_ratio"],
        short_interest=results.get("short_interest"),
        insider_trading=results.get("insider_trading"),
        composite_fraud_risk_score=results["composite_fraud_risk_score"],
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

    return ReportResponse(tickers=ticker_list, report_markdown=report_md)


# ---------------------------------------------------------------------------
# Entry-point (uvicorn main:app --reload  OR  python main.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
