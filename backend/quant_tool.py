from databricks import sql
import os
import sys
import argparse
import json

# Import pipeline modules
import sec as sec_module
import quant_metrics as qm

### Example usage: python quant_tool.py --ticker TIO 

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# -------------------------
# Databricks helpers
# -------------------------

def get_connection():
    return sql.connect(
        server_hostname="dbc-8d2119a9-8a9f.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/caf31424be59761a",
        access_token=os.environ.get("databricks_sql_pa"),
    )


def ensure_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            Ticker                     STRING,
            company_name               STRING,
            m_score                    DOUBLE,
            z_score                    DOUBLE,
            accruals_ratio             DOUBLE,
            composite_fraud_risk_score DOUBLE,
            last_updated               TIMESTAMP
        )
    """)


def upsert_to_databricks(cursor, ticker: str, company_name: str, results: dict):
    merge_sql = """
        MERGE INTO stocks AS t
        USING (
            SELECT
                :ticker                     AS Ticker,
                :company_name               AS company_name,
                :m_score                    AS m_score,
                :z_score                    AS z_score,
                :accruals_ratio             AS accruals_ratio,
                :composite_fraud_risk_score AS composite_fraud_risk_score,
                current_timestamp()         AS last_updated
        ) AS s
        ON t.Ticker = s.Ticker

        WHEN MATCHED AND t.last_updated < current_timestamp() - INTERVAL 1 DAY THEN
            UPDATE SET
                t.company_name               = s.company_name,
                t.m_score                    = s.m_score,
                t.z_score                    = s.z_score,
                t.accruals_ratio             = s.accruals_ratio,
                t.composite_fraud_risk_score = s.composite_fraud_risk_score,
                t.last_updated               = s.last_updated

        WHEN NOT MATCHED THEN
            INSERT (Ticker, company_name, m_score, z_score, accruals_ratio, composite_fraud_risk_score, last_updated)
            VALUES (s.Ticker, s.company_name, s.m_score, s.z_score, s.accruals_ratio, s.composite_fraud_risk_score, s.last_updated)
    """

    cursor.execute(merge_sql, parameters={
        "ticker":                     ticker,
        "company_name":               company_name,
        "m_score":                    results["m_score"],
        "z_score":                    results["z_score"],
        "accruals_ratio":             results["accruals_ratio"],
        "composite_fraud_risk_score": results["composite_fraud_risk_score"],
    })

    if cursor.rowcount == 0:
        print(f"[WARN] Row for {ticker} is already up-to-date (written today). Skipping write.")
    else:
        print(f"[OK] Upserted {ticker} into stocks table.")


# -------------------------
# Stock Health helpers
# -------------------------

def ensure_health_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_health (
            Ticker                       STRING,
            sharpe                       DOUBLE,
            sortino                      DOUBLE,
            alpha                        DOUBLE,
            beta                         DOUBLE,
            var_95                       DOUBLE,
            cvar_95                      DOUBLE,
            max_drawdown                 DOUBLE,
            volatility                   DOUBLE,
            composite_stock_health_score DOUBLE,
            last_updated                 TIMESTAMP
        )
    """)


def upsert_health_to_databricks(cursor, ticker: str, health: dict):
    merge_sql = """
        MERGE INTO stock_health AS t
        USING (
            SELECT
                :ticker                       AS Ticker,
                :sharpe                       AS sharpe,
                :sortino                      AS sortino,
                :alpha                        AS alpha,
                :beta                         AS beta,
                :var_95                       AS var_95,
                :cvar_95                      AS cvar_95,
                :max_drawdown                 AS max_drawdown,
                :volatility                   AS volatility,
                :composite_stock_health_score AS composite_stock_health_score,
                current_timestamp()           AS last_updated
        ) AS s
        ON t.Ticker = s.Ticker

        WHEN MATCHED AND t.last_updated < current_timestamp() - INTERVAL 1 DAY THEN
            UPDATE SET
                t.sharpe                       = s.sharpe,
                t.sortino                      = s.sortino,
                t.alpha                        = s.alpha,
                t.beta                         = s.beta,
                t.var_95                       = s.var_95,
                t.cvar_95                      = s.cvar_95,
                t.max_drawdown                 = s.max_drawdown,
                t.volatility                   = s.volatility,
                t.composite_stock_health_score = s.composite_stock_health_score,
                t.last_updated                 = s.last_updated

        WHEN NOT MATCHED THEN
            INSERT (Ticker, sharpe, sortino, alpha, beta, var_95, cvar_95,
                    max_drawdown, volatility, composite_stock_health_score, last_updated)
            VALUES (s.Ticker, s.sharpe, s.sortino, s.alpha, s.beta, s.var_95, s.cvar_95,
                    s.max_drawdown, s.volatility, s.composite_stock_health_score, s.last_updated)
    """
    cursor.execute(merge_sql, parameters={
        "ticker":                       ticker,
        "sharpe":                       health["sharpe"],
        "sortino":                      health["sortino"],
        "alpha":                        health["alpha"],
        "beta":                         health["beta"],
        "var_95":                       health["var_95"],
        "cvar_95":                      health["cvar_95"],
        "max_drawdown":                 health["max_drawdown"],
        "volatility":                   health["volatility"],
        "composite_stock_health_score": health["composite_stock_health_score"],
    })
    if cursor.rowcount == 0:
        print(f"[WARN] stock_health row for {ticker} is already up-to-date. Skipping write.")
    else:
        print(f"[OK] Upserted {ticker} into stock_health table.")


def upsert_health_to_databricks_safe(ticker: str, health: dict):
    """Self-contained wrapper: opens its own Databricks connection, upserts, closes.
    Intended for callers (e.g. main.py endpoints) that don't hold an open cursor.
    Silently logs errors instead of raising so a DB outage never kills an API response.
    """
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            ensure_health_table(cursor)
            upsert_health_to_databricks(cursor, ticker, health)
        conn.close()
    except Exception as exc:
        print(f"[WARN] Could not persist health metrics for {ticker} to Databricks: {exc}")


# -------------------------
# User + Portfolio helpers
# -------------------------

def ensure_users_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            phone      STRING,
            name       STRING,
            created_at TIMESTAMP
        )
    """)


def ensure_portfolio_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_portfolio (
            phone    STRING,
            ticker   STRING,
            added_at TIMESTAMP
        )
    """)


def upsert_user(cursor, phone: str, name: str):
    """Insert user if not exists (idempotent — never overwrites name)."""
    cursor.execute("""
        MERGE INTO users AS t
        USING (SELECT :phone AS phone, :name AS name) AS s
        ON t.phone = s.phone
        WHEN NOT MATCHED THEN
            INSERT (phone, name, created_at)
            VALUES (s.phone, s.name, current_timestamp())
    """, parameters={"phone": phone, "name": name})
    print(f"[OK] User {phone} registered (or already existed).")


def add_to_portfolio(cursor, phone: str, tickers: list):
    """Add tickers to a user's portfolio — duplicates silently ignored."""
    for ticker in tickers:
        cursor.execute("""
            MERGE INTO user_portfolio AS t
            USING (SELECT :phone AS phone, :ticker AS ticker) AS s
            ON t.phone = s.phone AND t.ticker = s.ticker
            WHEN NOT MATCHED THEN
                INSERT (phone, ticker, added_at)
                VALUES (s.phone, s.ticker, current_timestamp())
        """, parameters={"phone": phone, "ticker": ticker.upper()})
    print(f"[OK] Added {len(tickers)} ticker(s) to portfolio for {phone}.")


def read_user(cursor, phone: str):
    """Return user record dict or None if not found."""
    cursor.execute(
        "SELECT phone, name FROM users WHERE phone = :phone",
        parameters={"phone": phone},
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {"phone": row[0], "name": row[1]}


def read_portfolio(cursor, phone: str) -> list:
    """Return portfolio entries with latest fraud + health scores from Databricks."""
    cursor.execute("""
        SELECT
            up.ticker,
            s.composite_fraud_risk_score,
            sh.composite_stock_health_score,
            COALESCE(s.last_updated, sh.last_updated) AS last_updated
        FROM user_portfolio up
        LEFT JOIN stocks       s  ON up.ticker = s.Ticker
        LEFT JOIN stock_health sh ON up.ticker = sh.Ticker
        WHERE up.phone = :phone
        ORDER BY up.added_at
    """, parameters={"phone": phone})
    rows = cursor.fetchall()
    return [
        {
            "ticker":                       r[0],
            "composite_fraud_risk_score":   r[1],
            "composite_stock_health_score": r[2],
            "last_updated":                 str(r[3]) if r[3] else None,
        }
        for r in rows
    ]


# -------------------------
# Pipeline
# -------------------------

def run_pipeline(ticker_input: str):
    # 1. Resolve ticker → CIK + company name
    ticker_input = ticker_input.upper()
    cik, official_name, ticker = sec_module.get_cik_from_ticker(ticker_input)
    if not cik:
        print(f"[ERROR] Ticker '{ticker_input}' not found in tickers.json.")
        sys.exit(1)
    ticker = str(ticker)

    print(f"[INFO] Company : {official_name}")
    print(f"[INFO] Ticker  : {ticker}")
    print(f"[INFO] CIK     : {cik}")

    # 2. Fetch SEC data (skip if JSON already exists)
    sec_json_path = os.path.join(BACKEND_DIR, f"{ticker}_SEC.json")
    if os.path.exists(sec_json_path):
        print(f"[INFO] {sec_json_path} already exists — skipping SEC fetch.")
    else:
        print("[INFO] Fetching SEC filings...")
        filings = sec_module.get_required_filings(cik)
        filings = sec_module.enrich_with_metrics(cik, filings, ticker)

        fy_list = [f["year"] for f in filings["10K"]]
        latest_fy = max(fy_list)
        output = {
            "company": official_name,
            "cik": cik,
            "ticker": ticker,
            "10K_latest_and_prior": [
                tenk for tenk in filings["10K"]
                if tenk["year"] in (latest_fy, latest_fy - 1)
            ],
            "all_8K_until_1yr_back": filings["8K"],
            "Form4_this_year_only": filings["Form4"],
        }
        with open(sec_json_path, "w") as f:
            json.dump(output, f, indent=4)
        print(f"[INFO] Saved {sec_json_path}")

    # 3. Fetch insider data (hard-fail if sec_api key missing — checked at startup)
    insider_json_path = os.path.join(BACKEND_DIR, f"{ticker}_insider_data.json")
    if os.path.exists(insider_json_path):
        print(f"[INFO] {insider_json_path} already exists — skipping insider fetch.")
    else:
        print("[INFO] Fetching insider (Form 4) data...")
        sec_module.process_form4_insiders(ticker)
        print(f"[INFO] Saved {insider_json_path}")

    # 4. Calculate metrics
    print("[INFO] Calculating fraud-risk metrics...")
    results = qm.quant_metrics(ticker)

    print(f"  M-Score              : {results['m_score']:.4f}")
    print(f"  Z-Score              : {results['z_score']:.4f}")
    print(f"  Accruals Ratio       : {results['accruals_ratio']:.4f}")
    print(f"  Composite Fraud Risk : {results['composite_fraud_risk_score']} / 100")

    # 5. Upsert to Databricks
    print("[INFO] Connecting to Databricks...")
    conn = get_connection()
    cursor = conn.cursor()
    try:
        ensure_table(cursor)
        
        upsert_to_databricks(cursor, ticker, official_name or "", results)
    finally:
        cursor.close()
        conn.close()

    return ticker, official_name, results


# -------------------------
# CLI
# -------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run the full SEC → metrics → Databricks pipeline for a company."
    )
    parser.add_argument(
        "--ticker",
        type=str,
        required=True,
        help='Stock ticker to look up, e.g. "AAPL"',
    )
    args = parser.parse_args()

    # Hard-fail early if required env vars are absent
    missing = [v for v in ("databricks_sql_pa", "sec_api") if not os.environ.get(v)]
    if missing:
        print(f"[ERROR] Missing required environment variable(s): {', '.join(missing)}")
        sys.exit(1)

    ticker, company_name, results = run_pipeline(args.ticker)
    print(f"\n[DONE] {ticker} ({company_name}) — composite fraud risk score: {results['composite_fraud_risk_score']} / 100")


if __name__ == "__main__":
    main()