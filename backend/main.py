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

import os
import traceback
from typing import Any, List, Optional

import requests as http_requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from twilio.rest import Client as TwilioClient

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
# Global exception handler — always return JSON, never HTML
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class StockResponse(BaseModel):
    ticker: str
    company_name: Optional[str]
    m_score: Optional[float]
    z_score: Optional[float]
    accruals_ratio: Optional[float]
    short_interest: Any          # nested dict from quant_metrics
    insider_trading: Any         # nested dict from quant_metrics
    composite_fraud_risk_score: Optional[float]


class StockError(BaseModel):
    ticker: str
    error: str


class MultiStockResponse(BaseModel):
    results: List[StockResponse]
    errors: List[StockError]   # tickers that failed, with the reason


class ReportResponse(BaseModel):
    tickers: List[str]
    report_markdown: str


class HealthScoreResponse(BaseModel):
    ticker: str
    sharpe: Optional[float]
    sortino: Optional[float]
    alpha: Optional[float]
    beta: Optional[float]
    var_95: Optional[float]
    cvar_95: Optional[float]
    max_drawdown: Optional[float]
    volatility: Optional[float]
    composite_stock_health_score: Optional[float]


class HealthScoreError(BaseModel):
    ticker: str
    error: str


class MultiHealthScoreResponse(BaseModel):
    results: List[HealthScoreResponse]
    errors: List[HealthScoreError]


class CallRequest(BaseModel):
    phone: str
    message: str


class CallResponse(BaseModel):
    status: str
    sid: str


class HealthResponse(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["Meta"])
def health():
    """Liveness check."""
    return HealthResponse(status="ok")


# ---------------------------------------------------------------------------
# Voice call helpers
# ---------------------------------------------------------------------------

AUDIO_FILE = "speech.mp3"

@app.get("/audio")
def serve_audio():
    """Serve the generated MP3 to Twilio"""
    return FileResponse(AUDIO_FILE, media_type="audio/mpeg")

@app.get("/twiml")
def twiml(phone: str):
    """Return proper TwiML for Twilio to play the audio"""
    audio_url = f"{os.environ['BASE_URL']}/audio"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
</Response>"""
    return Response(content=xml, media_type="text/xml")

def _generate_voice(text: str, out_path: str = "speech.mp3") -> None:
    api_key = os.environ["ELEVEN_API_KEY"]
    voice_id = os.environ["ELEVEN_VOICE_ID"]
    resp = http_requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs error: {resp.text}")
    with open(out_path, "wb") as f:
        f.write(resp.content)


def _upload_audio(file_path: str) -> str:
    """Upload to litterbox.catbox.moe (expires in 1 h) and return the public URL."""
    with open(file_path, "rb") as f:
        resp = http_requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "1h"},
            files={"fileToUpload": ("speech.mp3", f, "audio/mpeg")},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Audio upload error {resp.status_code}: {resp.text}")
    url = resp.text.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"Unexpected upload response: {url}")
    return url


@app.post("/call", response_model=CallResponse, tags=["Voice"])
def make_call(body: CallRequest):
    try:
        _generate_voice(body.message)
        audio_url = _upload_audio(AUDIO_FILE)

        twilio_client = TwilioClient(
            os.environ["TWILIO_ACCOUNT_SID"],
            os.environ["TWILIO_AUTH_TOKEN"]
        )

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
</Response>"""

        call = twilio_client.calls.create(
            to=body.phone,
            from_=os.environ.get("TWILIO_PHONE_NUMBER"),
            twiml=xml  # pass TwiML inline instead of a callback URL
        )

        return CallResponse(status="sent", sid=call.sid)

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Call failed — check server logs.")


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
                m_score=res.get("m_score"),
                z_score=res.get("z_score"),
                accruals_ratio=res.get("accruals_ratio"),
                short_interest=res.get("short_interest"),
                insider_trading=res.get("insider_trading"),
                composite_fraud_risk_score=res.get("composite_fraud_risk_score"),
            ))
        except (SystemExit, ValueError):
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
        return StockResponse(
            ticker=resolved_ticker,
            company_name=company_name,
            m_score=results.get("m_score"),
            z_score=results.get("z_score"),
            accruals_ratio=results.get("accruals_ratio"),
            short_interest=results.get("short_interest"),
            insider_trading=results.get("insider_trading"),
            composite_fraud_risk_score=results.get("composite_fraud_risk_score"),
        )
    except (SystemExit, ValueError):
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Pipeline failed — check server logs.")


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
    report covering news sentiment, quantitative fraud risk metrics, and
    stock health metrics.

    Returns a JSON object with:
    - **tickers**: the tickers analysed
    - **report_markdown**: the full formal report in markdown
    - **summary**: a 1-2 paragraph executive summary

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
# Stock health endpoints
# ---------------------------------------------------------------------------

@app.get(
    "/health-score",
    response_model=MultiHealthScoreResponse,
    tags=["Health"],
    summary="Run the health-score pipeline for multiple tickers in one call",
)
def get_health_scores(
    tickers: str = Query(
        ...,
        description="Comma-separated ticker symbols, e.g. `NVDA,AAPL,DELL`",
        examples=["NVDA,AAPL,DELL"],
    )
):
    """
    Computes stock-health metrics (Sharpe, Sortino, Alpha, Beta, VaR, CVaR,
    Max Drawdown, Volatility, Composite Score) for each ticker in the
    comma-separated **tickers** query param.

    Tickers that fail (not found, no price data) are collected in the
    `errors` list so one bad ticker never blocks the rest.

    - **tickers**: comma-separated ticker symbols, e.g. `NVDA,AAPL,DELL`
    """
    ticker_list: List[str] = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="No valid tickers provided.")

    results: List[HealthScoreResponse] = []
    errors: List[HealthScoreError] = []

    for ticker in ticker_list:
        try:
            res = stock_health.compute_health(ticker)
            results.append(HealthScoreResponse(
                ticker=res["ticker"],
                sharpe=res.get("sharpe"),
                sortino=res.get("sortino"),
                alpha=res.get("alpha"),
                beta=res.get("beta"),
                var_95=res.get("var_95"),
                cvar_95=res.get("cvar_95"),
                max_drawdown=res.get("max_drawdown"),
                volatility=res.get("volatility"),
                composite_stock_health_score=res.get("composite_stock_health_score"),
            ))
        except (SystemExit, ValueError):
            errors.append(HealthScoreError(ticker=ticker, error="Ticker not found."))
        except Exception as exc:
            traceback.print_exc()
            errors.append(HealthScoreError(ticker=ticker, error=str(exc)))

    if not results and errors:
        raise HTTPException(
            status_code=422,
            detail=[e.dict() for e in errors],
        )

    return MultiHealthScoreResponse(results=results, errors=errors)


@app.get(
    "/health-score/{ticker}",
    response_model=HealthScoreResponse,
    tags=["Health"],
    summary="Run the health-score pipeline for a single ticker",
)
def get_health_score(ticker: str):
    """
    Computes stock-health metrics for **ticker** and returns all computed
    performance and risk metrics.

    - **ticker**: stock ticker symbol, e.g. `AAPL`
    """
    ticker = ticker.upper()
    try:
        res = stock_health.compute_health(ticker)
        return HealthScoreResponse(
            ticker=res["ticker"],
            sharpe=res.get("sharpe"),
            sortino=res.get("sortino"),
            alpha=res.get("alpha"),
            beta=res.get("beta"),
            var_95=res.get("var_95"),
            cvar_95=res.get("cvar_95"),
            max_drawdown=res.get("max_drawdown"),
            volatility=res.get("volatility"),
            composite_stock_health_score=res.get("composite_stock_health_score"),
        )
    except (SystemExit, ValueError):
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Health score pipeline failed — check server logs.")


# ---------------------------------------------------------------------------
# Static frontend — must be mounted AFTER all API routes
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")


# ---------------------------------------------------------------------------
# Entry-point (uvicorn main:app --reload  OR  python main.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5000,
        reload=True,
        http="httptools",
    )