import requests
import json
import os
import sys
from datetime import datetime, timedelta

# -------------------------
# SEC headers and URLs
# -------------------------
HEADERS = {
    "User-Agent": "YourName your.email@example.com",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}

LOCAL_TICKERS_FILE = "tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
BASE_URL = "https://data.sec.gov/submissions/"

# -------------------------
# GAAP Tag Fallback Dictionary
# -------------------------
GAAP_TAGS = {
    "net_receivables": ["AccountsReceivableNetCurrent", "AccountsReceivableNetTradeCurrent"],
    "cogs": ["CostOfGoodsAndServicesSold"],
    "current_assets": ["AssetsCurrent"],
    "ppe": ["PropertyPlantAndEquipmentNet"],
    "securities": ["AvailableForSaleSecuritiesCurrent", "MarketableSecuritiesCurrent"],
    "total_assets": ["Assets"],
    "depreciation": ["DepreciationDepletionAndAmortization", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment"],
    "sg&a": ["SellingGeneralAndAdministrativeExpense"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "income_continuing_ops": ["IncomeLossFromContinuingOperations", "IncomeLossFromContinuingOperationsBeforeIncomeTaxes", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"],
    "cash_from_ops": ["NetCashProvidedByUsedInOperatingActivities"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "gross_profit": ["GrossProfit"],
    "revenue": ["Revenues", "SalesRevenueNet", "SalesRevenueServicesNet", "RevenueFromContractWithCustomerExcludingAssessedTax"]
    # Market value of equity will require external stock price and shares outstanding
}

# -------------------------
# Utilities
# -------------------------
def get_cik_from_company_name(company_name):
    if not os.path.exists(LOCAL_TICKERS_FILE):
        print(f"Error: {LOCAL_TICKERS_FILE} not found.")
        sys.exit(1)

    with open(LOCAL_TICKERS_FILE, "r") as f:
        data = json.load(f)

    company_name = company_name.lower()
    for entry in data.values():
        if company_name in entry["title"].lower():
            return str(entry["cik_str"]).zfill(10), entry["title"]

    return None, None


def fetch_json(url):
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()


def extract_metric(companyfacts_json, tags, fy, form="10-K"):
    """Try multiple tags in order until one is found."""
    for tag in tags:
        fact = companyfacts_json.get("facts", {}).get("us-gaap", {}).get(tag)
        if not fact:
            continue
        data_entries = fact.get("units", {}).get("USD", [])
        for entry in data_entries:
            if entry.get("form") == form and entry.get("fy") == fy:
                return entry.get("val")
    return None


# -------------------------
# Filing processing
# -------------------------
def process_block(submissions_json, state):
    filings = submissions_json.get("filings", {}).get("recent", {})
    forms = filings.get("form", [])
    filing_dates = filings.get("filingDate", [])
    accession_numbers = filings.get("accessionNumber", [])
    primary_docs = filings.get("primaryDocument", [])

    current_year = datetime.today().year
    one_year_ago = datetime.today() - timedelta(days=365)

    for form, date_str, accession, doc in zip(forms, filing_dates, accession_numbers, primary_docs):
        filing_date = datetime.strptime(date_str, "%Y-%m-%d")
        filing_year = filing_date.year

        filing_entry = {
            "form": form,
            "filing_date": date_str,
            "accession_number": accession,
            "primary_document": doc,
            "filing_url": f"https://www.sec.gov/Archives/edgar/data/"
                          f"{int(submissions_json['cik'])}/"
                          f"{accession.replace('-', '')}/{doc}"
        }

        # ---- 10-K ----
        if form == "10-K":
            if filing_year not in [f["year"] for f in state["10K"]]:
                state["10K"].append({"year": filing_year, **filing_entry})

        # ---- 8-K ----
        elif form == "8-K":
            state["8K"].append(filing_entry)
            if filing_date <= one_year_ago:
                state["found_old_8k"] = True

        # ---- Form 4 (this year only) ----
        elif form == "4" and filing_year == current_year:
            state["Form4"].append(filing_entry)

    return state


def requirements_met(state):
    return len(state["10K"]) >= 2 and state["found_old_8k"]


def get_required_filings(cik):
    state = {"10K": [], "8K": [], "Form4": [], "found_old_8k": False}

    main_json = fetch_json(SUBMISSIONS_URL.format(cik=cik))
    state = process_block(main_json, state)

    if not requirements_met(state):
        older_files = main_json.get("filings", {}).get("files", [])
        for file_info in older_files:
            older_json = fetch_json(BASE_URL + file_info["name"])
            state = process_block(older_json, state)
            if requirements_met(state):
                break

    # Sort 10-Ks newest first
    state["10K"] = sorted(state["10K"], key=lambda x: x["filing_date"], reverse=True)
    # Sort 8-Ks newest first
    state["8K"] = sorted(state["8K"], key=lambda x: x["filing_date"], reverse=True)

    return state


# -------------------------
# Extract financial metrics
# -------------------------
def enrich_with_metrics(cik, filings):
    companyfacts = fetch_json(COMPANYFACTS_URL.format(cik=cik))

    # Determine the current FY (latest 10-K year)
    fy_list = [tenk["year"] for tenk in filings["10K"]]
    if not fy_list:
        return filings
    latest_fy = max(fy_list)
    prior_fy = latest_fy - 1

    # Keep metrics for both years
    for tenk in filings["10K"]:
        fy = tenk["year"]
        if fy not in [latest_fy, prior_fy]:
            continue  # skip other years

        metrics = {}
        for key, tags in GAAP_TAGS.items():
            metrics[key] = extract_metric(companyfacts, tags, fy)

        # Compute ratios
        # total_assets = metrics.get("total_assets")
        # metrics["working_cap_over_total_assets"] = (
        #     (metrics.get("current_assets", 0) - metrics.get("current_liabilities", 0)) / total_assets
        # ) if total_assets else None

        # metrics["retained_over_total_assets"] = (
        #     metrics.get("retained_earnings", 0) / total_assets
        # ) if total_assets else None

        # metrics["ebit_over_total_assets"] = (
        #     metrics.get("ebit", 0) / total_assets
        # ) if total_assets else None

        # metrics["sales_over_total_assets"] = (
        #     metrics.get("sales", 0) / total_assets
        # ) if total_assets else None

        # Market value of equity / total liabilities (external data required)
        metrics["market_equity_over_liabilities"] = None

        tenk["metrics"] = metrics

    return filings


# -------------------------
# Main
# -------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py \"Company Name\"")
        sys.exit(1)

    company_name = sys.argv[1]
    cik, official_name = get_cik_from_company_name(company_name)

    if not cik:
        print("Company not found.")
        sys.exit(1)

    print(f"Found company: {official_name}")
    print(f"CIK: {cik}")

    filings = get_required_filings(cik)
    filings = enrich_with_metrics(cik, filings)

    output = {
        "company": official_name,
        "cik": cik,
        "10K_latest_and_prior": [tenk for tenk in filings["10K"] if tenk["year"] in [
            max([f["year"] for f in filings["10K"]]),
            max([f["year"] for f in filings["10K"]])-1
        ]],
        "all_8K_until_1yr_back": filings["8K"],
        "Form4_this_year_only": filings["Form4"]
    }

    filename = f"{official_name.replace(' ', '_')}_SEC_combined.json"
    with open(filename, "w") as f:
        json.dump(output, f, indent=4)

    print(f"Saved results to {filename}")


if __name__ == "__main__":
    main()