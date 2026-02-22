import numpy as np
import json
from datetime import date
import yfinance as yf

### The goal of this python is to take the filtered SEC fillings and calculate the financial metrics for fraud detection.
### We will normalize each variable, weigh them and combine them into a single composite score 0 - 100
### The metrics we will calculate are: Benshi M-Score, Altman Z-Score, Accruals ratio, Benfords Law 

def load_data(ticker: str):
    """
    Load the filtered SEC filings data from the previous step
    we will do it for the past 2 years 
    """
    current_year = date.today().year

    # open the companies SEC Filings data 
    with open(f"{ticker}_SEC.json", "r") as f:
        raw = json.load(f)

    company_info = {
        "company": raw["company"],
        "cik": raw["cik"],  
        "ticker": raw["ticker"]
    }

    filings = raw["10K_latest_and_prior"]
    data_t = next(f["metrics"] for f in filings if f["year"] == current_year-4)
    data_t1 = next(f["metrics"] for f in filings if f["year"] == current_year-5)
    return data_t, data_t1, company_info

def M_score(data_t, data_t1):
    """
    calulate beneshi m_score for fraud detection from SEC filings
    input: net receivables, sales, cost of goods sold, PP&E, current assets, 
    securities, total assets, SG&G, Expenses, Sales, current liabiliities, total-long term debt, 
    income from continuing operations, cash flow from operations
    M-Score > -1.78 is likely to be a manipulator
    M-Score < -2.5 is a pefect company
    """
    if data_t["securities"] is None:
        data_t["securities"] = 0
    if data_t1["securities"] is None:
        data_t1["securities"] = 0
    if data_t["gross_profit"] is None:
        data_t["gross_profit"] = data_t["revenue"] - data_t["cogs"] if data_t["cogs"] is not None else 0
    if data_t1["gross_profit"] is None:
        data_t1["gross_profit"] = data_t1["revenue"] - data_t1["cogs"] if data_t1["cogs"] is not None else 0
    

    DSRI = (data_t["net_receivables"] / data_t["revenue"]) / (data_t1["net_receivables"] / data_t1["revenue"]) if data_t1["revenue"] != 0 else 0
    GMI = ((data_t1["revenue"] - data_t1["cogs"]) / data_t1["revenue"]) / ((data_t["revenue"] - data_t["cogs"]) / data_t["revenue"]) if data_t1["revenue"] != 0 and data_t["revenue"] != 0 else 0
    AQI = (1-(data_t["current_assets"] + data_t["ppe"] + data_t["securities"])/data_t["total_assets"]) / (1 - (data_t1["current_assets"] + data_t1["ppe"] + data_t1["securities"]) / data_t1["total_assets"]) if data_t1["total_assets"] != 0 and data_t["total_assets"] != 0 else 0 
    SGI = data_t["revenue"] / data_t1["revenue"] if data_t1["revenue"] != 0 else 0
    DEPI = (data_t1["depreciation"] / (data_t1["ppe"] + data_t1["depreciation"])) / (data_t["depreciation"] / (data_t["ppe"] + data_t["depreciation"])) if (data_t1["ppe"] + data_t1["depreciation"]) != 0 and (data_t["ppe"] + data_t["depreciation"]) != 0 else 0
    SGAI = (data_t["sg&a"] / data_t["revenue"]) / (data_t1["sg&a"] / data_t1["revenue"]) if data_t["revenue"] != 0 and data_t1["revenue"] != 0 else 0
    LVGI = ((data_t["current_liabilities"] + data_t["long_term_debt"]) / data_t["total_assets"]) / (data_t1["current_liabilities"] + data_t1["long_term_debt"]) * data_t1["total_assets"] if data_t1["total_assets"] != 0 else 0
    TATA = (data_t["income_continuing_ops"] - data_t["cash_from_ops"]) / data_t["total_assets"] if data_t["total_assets"] != 0 else 0
    m_score = -4.84 + 0.92*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI + 0.115*DEPI - 0.172*SGAI + 4.679*TATA - 0.327*LVGI
    return m_score;

def Altman_Z_score(data_t, data_t1):
    """
    calculate Altman Z-Score for fraud detection from SEC filings
    input: working capital, retained earnings, EBIT, market value of equity, total liabilities, total assets
    Z > 2.99 is safe 
    1.81 < Z < 2.99 is ok 
    Z < 1.81 is distress
    Jargon: sales == revenue, 
    For large companies where market cap can be 12x liablities this can cause the zscore to be a massive outlier. 
    """
    current_assets = data_t["current_assets"] or 0
    current_liabilities = data_t["current_liabilities"] or 0
    total_assets = data_t["total_assets"] or 0
    retained_earnings = data_t["retained_earnings"] or 0
    ebit = data_t["ebit"] or 0
    market_equity = data_t["market_equity"] or 0
    liabilities = data_t["liabilities"] or 0
    revenue = data_t["revenue"] or 0

    X1 = (current_assets - current_liabilities) / total_assets if total_assets != 0 else 0
    X2 = retained_earnings / total_assets if total_assets != 0 else 0
    X3 = ebit / total_assets if total_assets != 0 else 0
    X4 = market_equity / liabilities if liabilities != 0 else 0
    X5 = revenue / total_assets if total_assets != 0 else 0
    z_score = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5
    return z_score

def Accruals_ratio(data_t):
    """
    calculate accruals ratio for fraud detection from SEC filings
    input: net income, cash flow from operations, total assets
    Accruals ratio > 0.1 is a red flag for potential earnings manipulation
    Interpretation:
        < 0.0  : Good — cash earnings exceed reported earnings
        0.0 - 0.10  : Neutral
        0.10 - 0.25 : Caution
        > 0.25 : Red flag — earnings disconnected from cash
    """
    net_income_loss = data_t["net_income_loss"] or 0
    cash_from_ops = data_t["cash_from_ops"] or 0
    accruals = net_income_loss - cash_from_ops
    accruals_ratio = accruals / data_t["total_assets"] if data_t["total_assets"] != 0 else 0
    return accruals_ratio

def short_interest(ticker_s): 
    """
    Score how interested people are in shorting the stock. This can be a signal of potential fraud if 
    there is a high level of short interest, as it may indicate that investors are betting against the company.
    """
    ticker = yf.Ticker(ticker_s)
    info = ticker.info
    
    shares_short = info.get("sharesShort", 0)
    float_shares = info.get("floatShares", 0)
    avg_volume = info.get("averageVolume", 0)
    
    short_ratio = info.get("shortRatio", 0)  # days to cover
    short_percent_of_float = info.get("shortPercentOfFloat", 0)
    
    return {
        "shares_short": shares_short,
        "short_percent_of_float": round(short_percent_of_float * 100, 2),
        "days_to_cover": short_ratio,
        "signal": classify_short_interest(short_percent_of_float, short_ratio)
    }

def classify_short_interest(pct_float, days_to_cover):
    if pct_float < 0.05 and days_to_cover < 3:
        return {"label": "Low Short Interest", "color": "green", "score": 10}
    elif pct_float < 0.10 and days_to_cover < 5:
        return {"label": "Moderate Short Interest", "color": "yellow", "score": 40}
    elif pct_float < 0.20 and days_to_cover < 10:
        return {"label": "High Short Interest", "color": "orange", "score": 70}
    else:
        return {"label": "Very High Short Interest", "color": "red", "score": 90} 
    

# TODO: Normalize Values, Assign weights and compute composite score for fraud risk
# TODO: make one big function that returns all the metrics and the composite score for fraud risk.

def insider_trading_activity(insider_data_path: str, lookback_days: int = 365) -> dict:
    """
    thank claude
    Analyse Form 4 filings and return the overall sale-to-purchase ratio
    and each insider's individual ratio.

    Only open-market sells (code "S") and buys (code "P") are counted.
    RSU vestings (M), tax-withholding disposals (F), and grants (A) are excluded.

    Note: for large-cap companies like Apple, insiders rarely buy on the open
    market — compensation comes through RSUs. When no purchases exist the ratio
    is meaningless, so total_sold_usd is the primary signal in that case.

    Returns
    -------
    {
        "overall_ratio":    float | "inf",
        "insider_ratios":   {name: float | "inf", ...},
        "insider_sold_usd": {name: float, ...}   # raw $ sold per insider
    }
    """
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    with open(insider_data_path, "r") as f:
        raw = json.load(f)

    sell_by_insider: dict[str, float] = {}
    buy_by_insider:  dict[str, float] = {}
    total_sales = 0.0
    total_buys  = 0.0

    for filing in raw.get("transactions", []):
        filed_at_str = filing.get("filedAt", "")
        try:
            filed_at = datetime.fromisoformat(filed_at_str)
            if filed_at.tzinfo is None:
                filed_at = filed_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        if filed_at < cutoff:
            continue

        owner = filing.get("reportingOwner", {}).get("name", "Unknown")

        for txn in filing.get("nonDerivativeTable", {}).get("transactions", []):
            code = txn.get("coding", {}).get("code", "")
            if code not in ("S", "P"):
                continue

            amounts = txn.get("amounts", {})
            shares  = float(amounts.get("shares", 0) or 0)
            price   = float(amounts.get("pricePerShare", 0) or 0)
            value   = shares * price

            if code == "S":
                sell_by_insider[owner] = sell_by_insider.get(owner, 0.0) + value
                total_sales += value
            else:
                buy_by_insider[owner]  = buy_by_insider.get(owner, 0.0) + value
                total_buys  += value

    all_insiders = set(sell_by_insider) | set(buy_by_insider)
    insider_ratios = {}
    for name in all_insiders:
        s = sell_by_insider.get(name, 0.0)
        b = buy_by_insider.get(name, 0.0)
        insider_ratios[name] = round(s / b, 2) if b > 0 else "inf"

    overall_ratio = round(total_sales / total_buys, 2) if total_buys > 0 else "inf"

    insider_sold_usd = {k: round(v, 2) for k, v in sell_by_insider.items()}
    avg_insider_sold_usd = round(sum(insider_sold_usd.values()) / len(insider_sold_usd), 2) if insider_sold_usd else 0.0

    return {
        "overall_ratio":       overall_ratio,
        "insider_ratios":      insider_ratios,
        "insider_sold_usd":    insider_sold_usd,
        "avg_insider_sold_usd": avg_insider_sold_usd,
    }




def normalize_and_combine_metrics(m_score, z_score, accruals_ratio, short_interest_score, overall_ratio, average_insider_sold_usd):
    
    # M-Score: higher (less negative) = more risk. Range [-4, 0]
    normalized_m_score = max(0, min(1, (m_score + 4) / 4))
    
    # Z-Score: INVERTED — lower score = more distress = more risk. Range [0, 3]
    normalized_z_score = max(0, min(1, 1 - (z_score / 3)))
    
    # Accruals: higher = more risk. Range [0, 0.25+]
    normalized_accruals_ratio = max(0, min(1, accruals_ratio / 0.25))
    
    # Short interest: already 0-1
    normalized_short_interest = max(0, min(1, short_interest_score))
    
    # Insider: sell/buy ratio or avg sold
    # var_x = min(1, average_insider_sold_usd / 1e6) if overall_ratio == "inf" else min(1, overall_ratio / 10)

    combined_score = (
        normalized_m_score  * 0.45 +
        normalized_z_score  * 0.35 +
        normalized_accruals_ratio * 0.20)
    
    return combined_score

def quant_metrics(ticker: str):
    data_t, data_t1, company_info = load_data(ticker=ticker)
    m_score_value = M_score(data_t, data_t1)
    z_score_value = Altman_Z_score(data_t, data_t1)
    accruals_ratio_value = Accruals_ratio(data_t)
    short_interest_value = short_interest(company_info['ticker'])
    insider = insider_trading_activity(f"{company_info['ticker']}_insider_data.json", lookback_days=365)

    composite_score = normalize_and_combine_metrics(
        m_score_value, 
        z_score_value, 
        accruals_ratio_value, 
        short_interest_value['signal']['score'] / 100,  # convert to 0-1
        insider['overall_ratio'] if insider['overall_ratio'] != "inf" else 1.0,  # treat inf as max risk
        insider['avg_insider_sold_usd']
    )

    return {
        "m_score": m_score_value,
        "z_score": z_score_value,
        "accruals_ratio": accruals_ratio_value,
        "short_interest": short_interest_value,
        "insider_trading": insider,
        "composite_fraud_risk_score": round(composite_score * 100, 2)  # Scale to 0-100
    }

def main():
    argparse = __import__("argparse")
    parser = argparse.ArgumentParser(description="Calculate financial metrics for fraud detection")
    parser.add_argument("--ticker", type=str, default="AAPL", help="Stock ticker symbol (default: AAPL)")
    args = parser.parse_args()
    data_t, data_t1, company_info = load_data(ticker=args.ticker)
    print(f"Loaded data for {company_info['company']} (CIK: {company_info['cik']})")
    print("Calculating financial metrics for fraud detection...")
    m_score_value = M_score(data_t, data_t1)
    print(f"Benshi M-Score: {m_score_value}")
    z_score_value = Altman_Z_score(data_t, data_t1)
    print(f"Altman Z-Score: {z_score_value}")
    accruals_ratio_value = Accruals_ratio(data_t)
    print(f"Accruals Ratio: {accruals_ratio_value}")
    short_interest_value = short_interest(company_info['ticker'])
    # print the risk score and label for short interest
    print(f"Short Interest: {short_interest_value['signal']['label']} (Score: {short_interest_value['signal']['score']})")

    # --- Insider Trading Activity (Form 4) ---
    insider = insider_trading_activity(f"{company_info['ticker']}_insider_data.json", lookback_days=365)
    print(f"Insider Trading Overall Ratio: {insider['overall_ratio']}")
    print(f"Insider Trading Individual Ratios: {insider['insider_ratios']}")
    print(f"Insider $ Sold: {insider['insider_sold_usd']}")
    print(f"Avg Insider $ Sold: {insider['avg_insider_sold_usd']}")

    # COMPOSITE SCORE
    composite_score = normalize_and_combine_metrics(
        m_score_value, 
        z_score_value, 
        accruals_ratio_value, 
        short_interest_value['signal']['score'] / 100,  # convert to 0-1
        insider['overall_ratio'] if insider['overall_ratio'] != "inf" else 1.0,  # treat inf as max risk
        insider['avg_insider_sold_usd']
    )
    print(f"Composite Fraud Risk Score: {round(composite_score * 100, 2)} / 100")



if __name__ == '__main__':
    main()