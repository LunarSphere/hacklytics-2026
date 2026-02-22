from databricks import sql
import os
import sys
import argparse
import json

# Import pipeline modules
import sec as sec_module
import quant_metrics as qm


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
    sec_json_path = f"{ticker}_SEC.json"
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
    insider_json_path = f"{ticker}_insider_data.json"
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
        upsert_to_databricks(cursor, ticker, official_name, results)
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