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
import threading
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


class CreateUserRequest(BaseModel):
    phone: str
    name: str


class UserPortfolioRequest(BaseModel):
    tickers: List[str]


class PortfolioEntry(BaseModel):
    ticker: str
    composite_fraud_risk_score: Optional[float] = None
    composite_stock_health_score: Optional[float] = None
    last_updated: Optional[str] = None


class UserResponse(BaseModel):
    phone: str
    name: str
    portfolio: List[PortfolioEntry]
    avg_fraud_score: Optional[float] = None
    avg_health_score: Optional[float] = None


class AlertCallResult(BaseModel):
    phone: str
    name: str
    status: str          # "sent" or "failed"
    detail: Optional[str] = None


class AlertResponse(BaseModel):
    ticker: str
    fraud_risk_score: float
    credibility_score: float
    alert_triggered: bool
    users_notified: int
    calls: List[AlertCallResult]


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
            from_=os.environ["TWILIO_PHONE_NUMBER"],
            twiml=xml  # pass TwiML inline instead of a callback URL
        )
        return CallResponse(status="sent", sid=call.sid or "")
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
            fraud_score = res.get("composite_fraud_risk_score")
            if fraud_score is not None:
                _maybe_alert(resolved_ticker, fraud_score)
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
        fraud_score = results.get("composite_fraud_risk_score")
        if fraud_score is not None:
            _maybe_alert(resolved_ticker, fraud_score)
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
    except Exception as e:
        print(f"Error generating report for tickers {ticker_list}: {e}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Report generation failed: {type(e).__name__}: {e}",
        )

    report_text = report_md.get("report", "") if isinstance(report_md, dict) else str(report_md)
    return ReportResponse(tickers=ticker_list, report_markdown=report_text)


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
# Insecure-stock alert endpoint
# ---------------------------------------------------------------------------

FRAUD_ALERT_THRESHOLD = 85.0  # composite_fraud_risk_score > 85  →  credibility < 15 %


def _maybe_alert(ticker: str, fraud_score: float) -> None:
    """Fire-and-forget: if fraud_score > FRAUD_ALERT_THRESHOLD, call every
    portfolio holder of *ticker* in a background thread so the API response
    is never delayed.
    """
    if fraud_score <= FRAUD_ALERT_THRESHOLD:
        return

    def _run():
        credibility = round(100.0 - fraud_score, 2)
        message = (
            f"Urgent alert from your portfolio monitor. "
            f"Stock {ticker} is currently insecure — you should sell it now. "
            f"Its fraud risk score is {round(fraud_score, 1)} out of 100, "
            f"giving a credibility score of only {credibility} percent. "
            f"Please review your portfolio immediately."
        )
        try:
            conn = quant_tool.get_connection()
            with conn.cursor() as cursor:
                quant_tool.ensure_users_table(cursor)
                quant_tool.ensure_portfolio_table(cursor)
                holders = quant_tool.get_users_holding_ticker(cursor, ticker)
            conn.close()
        except Exception:
            traceback.print_exc()
            return

        if not holders:
            print(f"[alert] {ticker} fraud score {fraud_score} — no holders to notify.")
            return

        print(f"[alert] {ticker} fraud score {fraud_score} (credibility {credibility}%) — calling {len(holders)} holder(s)")
        for user in holders:
            phone, name = user["phone"], user["name"]
            try:
                _generate_voice(message)
                audio_url = _upload_audio(AUDIO_FILE)
                twilio_client = TwilioClient(
                    os.environ["TWILIO_ACCOUNT_SID"],
                    os.environ["TWILIO_AUTH_TOKEN"],
                )
                xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
</Response>"""
                call = twilio_client.calls.create(
                    to=phone,
                    from_=os.environ["TWILIO_PHONE_NUMBER"],
                    twiml=xml,
                )
                print(f"[alert] Called {name} ({phone}) re {ticker} — SID {call.sid}")
            except Exception:
                traceback.print_exc()
                print(f"[alert] Failed to call {name} ({phone}) re {ticker}")

    threading.Thread(target=_run, daemon=True).start()


@app.post(
    "/alert/{ticker}",
    response_model=AlertResponse,
    tags=["Voice"],
    summary="Call all holders of a ticker if its credibility score is below 15 %",
)
def alert_insecure_stock(ticker: str):
    """
    Looks up the **composite_fraud_risk_score** for *ticker* in Databricks.
    Credibility is defined as ``100 − fraud_risk_score``.

    If credibility < 15 % (i.e. fraud score > 85), every registered user
    who holds that ticker in their portfolio receives an automated voice
    call warning them to sell.

    Returns a summary of the alert including every call attempt.
    """
    ticker = ticker.upper()

    # ── 1. Look up fraud score ────────────────────────────────────────────
    try:
        conn = quant_tool.get_connection()
        with conn.cursor() as cursor:
            quant_tool.ensure_users_table(cursor)
            quant_tool.ensure_portfolio_table(cursor)
            fraud_score = quant_tool.get_fraud_score_for_ticker(cursor, ticker)
            if fraud_score is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No fraud-risk data found for '{ticker}'. Run /stocks?tickers={ticker} first.",
                )
            holders = quant_tool.get_users_holding_ticker(cursor, ticker)
        conn.close()
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Databricks query failed — check server logs.")

    credibility = round(100.0 - fraud_score, 2)
    alert_triggered = fraud_score > FRAUD_ALERT_THRESHOLD

    call_results: List[AlertCallResult] = []

    if not alert_triggered:
        return AlertResponse(
            ticker=ticker,
            fraud_risk_score=round(fraud_score, 2),
            credibility_score=credibility,
            alert_triggered=False,
            users_notified=0,
            calls=[],
        )

    # ── 2. Call every holder ──────────────────────────────────────────────
    message = (
        f"Urgent alert from your portfolio monitor. "
        f"Stock {ticker} is currently insecure — you should sell it now. "
        f"Its fraud risk score is {round(fraud_score, 1)} out of 100, "
        f"giving a credibility score of only {credibility} percent. "
        f"Please review your portfolio immediately."
    )

    for user in holders:
        phone = user["phone"]
        name  = user["name"]
        try:
            _generate_voice(message)
            audio_url = _upload_audio(AUDIO_FILE)
            twilio_client = TwilioClient(
                os.environ["TWILIO_ACCOUNT_SID"],
                os.environ["TWILIO_AUTH_TOKEN"],
            )
            xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
</Response>"""
            call = twilio_client.calls.create(
                to=phone,
                from_=os.environ["TWILIO_PHONE_NUMBER"],
                twiml=xml,
            )
            print(f"[alert] Called {name} ({phone}) re {ticker} — SID {call.sid}")
            call_results.append(AlertCallResult(phone=phone, name=name, status="sent", detail=call.sid))
        except Exception as exc:
            traceback.print_exc()
            print(f"[alert] Failed to call {name} ({phone}): {exc}")
            call_results.append(AlertCallResult(phone=phone, name=name, status="failed", detail=str(exc)))

    return AlertResponse(
        ticker=ticker,
        fraud_risk_score=round(fraud_score, 2),
        credibility_score=credibility,
        alert_triggered=True,
        users_notified=sum(1 for r in call_results if r.status == "sent"),
        calls=call_results,
    )


# ---------------------------------------------------------------------------
# User + Portfolio endpoints
# ---------------------------------------------------------------------------

@app.post("/users", tags=["Users"], summary="Register a new user")
def create_user(body: CreateUserRequest):
    """
    Create a new user identified by **phone** number.
    Idempotent — calling again with the same phone never overwrites the name.
    """
    try:
        conn = quant_tool.get_connection()
        with conn.cursor() as cursor:
            quant_tool.ensure_users_table(cursor)
            quant_tool.upsert_user(cursor, body.phone, body.name)
        conn.close()
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Could not register user — check server logs.")
    return {"phone": body.phone, "name": body.name}


@app.post("/users/{phone}/portfolio", tags=["Users"], summary="Add tickers to a user's portfolio")
def add_to_portfolio(phone: str, body: UserPortfolioRequest):
    """
    Add one or more tickers to the portfolio of the user identified by **phone**.
    Duplicate tickers are silently ignored.
    """
    if not body.tickers:
        raise HTTPException(status_code=400, detail="No tickers provided.")
    try:
        conn = quant_tool.get_connection()
        with conn.cursor() as cursor:
            quant_tool.ensure_portfolio_table(cursor)
            quant_tool.add_to_portfolio(cursor, phone, body.tickers)
        conn.close()
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Could not update portfolio — check server logs.")
    return {"phone": phone, "tickers_added": [t.upper() for t in body.tickers]}


@app.get("/users/{phone}", response_model=UserResponse, tags=["Users"], summary="Get a user and their portfolio")
def get_user(phone: str):
    """
    Fetch user profile and their portfolio with the latest fraud + health scores
    for each ticker pulled from Databricks.
    Also returns **avg_fraud_score** and **avg_health_score** across the portfolio.
    """
    try:
        conn = quant_tool.get_connection()
        with conn.cursor() as cursor:
            quant_tool.ensure_users_table(cursor)
            quant_tool.ensure_portfolio_table(cursor)
            user = quant_tool.read_user(cursor, phone)
            if not user:
                raise HTTPException(status_code=404, detail=f"User '{phone}' not found.")
            portfolio_rows = quant_tool.read_portfolio(cursor, phone)
        conn.close()
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Could not fetch user — check server logs.")

    portfolio = [PortfolioEntry(**row) for row in portfolio_rows]
    fraud_scores  = [p.composite_fraud_risk_score  for p in portfolio if p.composite_fraud_risk_score  is not None]
    health_scores = [p.composite_stock_health_score for p in portfolio if p.composite_stock_health_score is not None]

    return UserResponse(
        phone=user["phone"],
        name=user["name"],
        portfolio=portfolio,
        avg_fraud_score=round(sum(fraud_scores)  / len(fraud_scores),  2) if fraud_scores  else None,
        avg_health_score=round(sum(health_scores) / len(health_scores), 2) if health_scores else None,
    )


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