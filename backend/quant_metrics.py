import numpy as np
import json
from datetime import date

### The goal of this python is to take the filtered SEC fillings and calculate the financial metrics for fraud detection.
### We will normalize each variable, weigh them and combine them into a single composite score 0 - 100
### The metrics we will calculate are: Benshi M-Score, Altman Z-Score, Accruals ratio, Benfords Law 

def load_data():
    """
    Load the filtered SEC filings data from the previous step
    we will do it for the past 2 years 
    """
    current_year = date.today().year

    # open the companies SEC Filings data 
    with open("AAPL_SEC_combined.json", "r") as f:
        raw = json.load(f)

    company_info = {
        "company": raw["company"],
        "cik": raw["cik"]
    }

    filings = raw["10K_latest_and_prior"]
    data_t = next(f["metrics"] for f in filings if f["year"] == current_year-1)
    data_t1 = next(f["metrics"] for f in filings if f["year"] == current_year-2)
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
    X1 = (data_t["current_assets"] - data_t["current_liabilities"]) / data_t["total_assets"] if data_t["total_assets"] != 0 else 0
    X2 = data_t["retained_earnings"] / data_t["total_assets"] if data_t["total_assets"] != 0 else 0
    X3 = data_t["ebit"] / data_t["total_assets"] if data_t["total_assets"] != 0 else 0
    X4 = (data_t["market_equity"]) / data_t["liabilities"] if data_t["liabilities"] != 0 else 0
    X5 = data_t["revenue"] / data_t["total_assets"] if data_t["total_assets"] != 0 else 0
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
    accruals = (data_t["net_income_loss"] - data_t["cash_from_ops"]) if data_t["cash_from_ops"] else 0
    accruals_ratio = accruals / data_t["total_assets"] if data_t["total_assets"] != 0 else 0
    return accruals_ratio



def main():
    data_t, data_t1, company_info = load_data()
    print(f"Loaded data for {company_info['company']} (CIK: {company_info['cik']})")
    print("Calculating financial metrics for fraud detection...")
    m_score_value = M_score(data_t, data_t1)
    print(f"Benshi M-Score: {m_score_value}")
    z_score_value = Altman_Z_score(data_t, data_t1)
    print(f"Altman Z-Score: {z_score_value}")
    accruals_ratio_value = Accruals_ratio(data_t)
    print(f"Accruals Ratio: {accruals_ratio_value}")

if __name__ == '__main__':
    main()