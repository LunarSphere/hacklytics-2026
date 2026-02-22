import requests
import json
import os
import sys
from datetime import datetime, timedelta
import yfinance as yf
import xml.etree.ElementTree as ET
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
# GAAP_TAGS = {
#     "net_receivables": ["AccountsReceivableNetCurrent", "AccountsReceivableNetTradeCurrent"],
#     "cogs": ["CostOfGoodsAndServicesSold"],
#     "current_assets": ["AssetsCurrent"],
#     "ppe": ["PropertyPlantAndEquipmentNet"],
#     "securities": ["AvailableForSaleSecuritiesCurrent", "MarketableSecuritiesCurrent"],
#     "total_assets": ["Assets"],
#     "depreciation": ["DepreciationDepletionAndAmortization", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment"],
#     "sg&a": ["SellingGeneralAndAdministrativeExpense"],
#     "current_liabilities": ["LiabilitiesCurrent"],
#     "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
#     "income_continuing_ops": ["IncomeLossFromContinuingOperations", "IncomeLossFromContinuingOperationsBeforeIncomeTaxes", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"], #pretax
#     "cash_from_ops": ["NetCashProvidedByUsedInOperatingActivities"],
#     "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
#     "gross_profit": ["GrossProfit"],
#     "revenue": ["Revenues", "SalesRevenueNet", "SalesRevenueServicesNet", "RevenueFromContractWithCustomerExcludingAssessedTax"],
#     "ebit": ["EarningsBeforeInterestAndTaxes", "OperatingIncomeLoss"],
#     "liabilities": ["Liabilities"],
#     "net_income_loss": ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"]
#     # Market value of equity will require external stock price and shares outstanding
# }

GAAP_TAGS = {

    "net_receivables": [
        "AccountsReceivableNetCurrent",                          # most common
        "ReceivablesNetCurrent",                                 # older filers
        "AccountsReceivableNet",                                 # some variations
        "AccountsReceivableNetTradeCurrent",
        "TradeAndOtherReceivablesNetCurrent",
        "AccountsNotesAndLoansReceivableNetCurrent",
        "NotesAndAccountsReceivableNet",
    ],

    "cogs": [
        "CostOfGoodsAndServicesSold",                           # post-2018 standard
        "CostOfRevenue",                                         # tech/service companies
        "CostOfGoodsSold",                                       # older manufacturing
        "CostOfSales",                                           # retail common
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
        "CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization",
        "CostsAndExpenses",                                      # last resort — broad
    ],

    "current_assets": [
        "AssetsCurrent",                                         # universal
        "AssetsTotalCurrent",                                    # rare variant
    ],

    "ppe": [
        "PropertyPlantAndEquipmentNet",                          # most common
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",  # post-ASC 842
        "PropertyPlantAndEquipmentNetIncludingFinanceLeases",
        "PropertyPlantAndEquipmentAndRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
        "PropertyAndEquipmentNet",                               # smaller filers
    ],

    "securities": [
        "AvailableForSaleSecuritiesCurrent",                     # pre-ASU 2016
        "MarketableSecuritiesCurrent",                           # tech companies (Apple)
        "ShortTermInvestments",                                  # very common alternative
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",       # post-ASU 2016
        "TradingSecuritiesCurrent",
        "InvestmentsFairValueDisclosure",
        "EquitySecuritiesFvNiCurrent",                           # post-ASU 2016 equity
        "DebtSecuritiesAvailableForSaleCurrent",
    ],

    "total_assets": [
        "Assets",                                                # universal — this never changes
    ],

    "depreciation": [
        "DepreciationDepletionAndAmortization",                  # most common in CF statement
        "DepreciationAndAmortization",                           # income statement version
        "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
        "Depreciation",                                          # pure depreciation no amortization
        "DepreciationAmortizationAndAccretionNet",
        "CostDepletionDepreciationAndAmortization",
        "AmortizationOfIntangibleAssets",                        # if D&A split out
        "DepreciationNonproduction",
    ],

    "sg&a": [
        "SellingGeneralAndAdministrativeExpense",                # most common
        "GeneralAndAdministrativeExpense",                       # G&A only (no selling)
        "SellingAndMarketingExpense",                            # selling only
        "SellingExpense",
        "OperatingExpenses",                                     # broad fallback — use with caution
        "OtherCostAndExpenseOperating",
        "SellingGeneralAndAdministrativeExpenseExcludingDepreciation",
        "NoninterestExpense",                                    # banking equivalent
    ],

    "current_liabilities": [
        "LiabilitiesCurrent",                                    # universal
        "LiabilitiesTotalCurrent",                               # rare variant
    ],

    "long_term_debt": [
        "LongTermDebtNoncurrent",                                # most common
        "LongTermDebt",                                          # includes current portion
        "LongTermDebtAndCapitalLeaseObligations",                # pre-ASC 842
        "LongTermDebtAndFinanceLeaseLiability",                  # post-ASC 842
        "LongTermNotesPayable",
        "SeniorLongTermNotes",
        "LongTermLineOfCredit",
        "ConvertibleLongTermNotesPayable",
        "LongTermDebtNoncurrentExcludingRelatedParties",
        "FinanceLeaseLiabilityNoncurrent",                       # lease obligations
        "OperatingLeaseLiabilityNoncurrent",                     # post-ASC 842
    ],

    "income_continuing_ops": [                                   # PRETAX — critical for TATA
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",  # most accurate
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
        "IncomeLossFromContinuingOperations",                    # after-tax fallback
        "ProfitLoss",                                            # IFRS filers
    ],

    "cash_from_ops": [
        "NetCashProvidedByUsedInOperatingActivities",            # most common
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "CashGeneratedFromOperations",                           # rare
        "NetCashFromOperatingActivities",
    ],

    "retained_earnings": [
        "RetainedEarningsAccumulatedDeficit",                    # most common — covers both positive and negative
        "RetainedEarnings",                                      # always profitable companies
        "AccumulatedDeficit",                                    # loss companies
        "RetainedEarningsUnappropriated",
    ],

    "gross_profit": [
        "GrossProfit",                                           # universal
        "GrossProfitLoss",                                       # rare variant
    ],

    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",   # 2019–present (ASC 606)
        "RevenueFromContractWithCustomerIncludingAssessedTax",   # with sales tax included
        "Revenues",                                              # 2018 transition year
        "SalesRevenueNet",                                       # pre-2018
        "SalesRevenueGoodsNet",                                  # goods only pre-2018
        "SalesRevenueServicesNet",                               # services only pre-2018
        "RevenueFromContractWithCustomer",
        "RevenuesNetOfInterestExpense",                          # banking
        "InterestAndDividendIncomeOperating",                    # banking alternative
        "NetInvestmentIncome",                                   # insurance/investment cos
        "PremiumsEarnedNet",                                     # insurance
        "HealthCareOrganizationRevenue",                         # healthcare
        "RealEstateRevenueNet",                                  # REITs
        "OilAndGasRevenue",                                      # energy sector
        "RevenueFromRelatedParties",                             # don't use — related party only
    ],

    "ebit": [
        "OperatingIncomeLoss",                                   # most common and reliable
        "EarningsBeforeInterestAndTaxes",                        # rare direct tag
        "IncomeLossFromContinuingOperationsBeforeInterestExpenseInterestIncomeIncomeTaxesExtraordinaryItemsNoncontrollingInterestsNet",
        "OperatingIncomeLossFromContinuingOperations",
        "IncomeLossFromOperations",
        "OperatingIncome",
    ],

    "liabilities": [
        "Liabilities",                                           # universal total liabilities
        "LiabilitiesAndStockholdersEquity",                      # do NOT use — this equals total assets
    ],

    "net_income_loss": [
        "NetIncomeLoss",                                         # most common
        "NetIncomeLossAvailableToCommonStockholdersBasic",       # after preferred dividends
        "NetIncomeLossAvailableToCommonStockholdersDiluted",
        "ProfitLoss",                                            # includes minority interest
        "NetIncomeLossAttributableToParent",
        "IncomeLossFromContinuingOperations",                    # excludes discontinued ops
        "ComprehensiveIncomeNetOfTax",                           # do NOT use for M-score — too broad
    ],

    # --- NEW FIELD from Ratmono et al. 2020 ---
    "roa_net_income": [                                          # for ΔROA calculation
        "NetIncomeLoss",                                         # same as net_income_loss
        "ProfitLoss",
    ],

    # --- SHARES OUTSTANDING (for market cap calculation) ---
    "shares_outstanding": [
        "CommonStockSharesOutstanding",                          # most common
        "EntityCommonStockSharesOutstanding",                    # DEI namespace not us-gaap
        "CommonStockSharesOutstandingIncludingTreasuryShares",
        "SharesOutstanding",
    ],

    # --- INCOME TAX (useful for deriving pretax from net income if needed) ---
    "income_tax_expense": [
        "IncomeTaxExpenseBenefit",                               # most common
        "CurrentIncomeTaxExpenseBenefit",
        "IncomeTaxesPaidNet",                                    # cash basis fallback
    ],
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
            return str(entry["cik_str"]).zfill(10), entry["title"], entry["ticker"]

    return None, None, None


def process_form4_insiders(ticker):
    insider_data = {}

    file_name = f"{ticker}_insider_data.json"
    if not os.path.exists(file_name):

        endpoint = "https://api.sec-api.io/insider-trading"
        params = {
            "query": f"issuer.tradingSymbol:{ticker}",
            "from": "0",
            "size": "50",
            "sort": [{ "filedAt": { "order": "desc" } }]
        }

        response = requests.post(endpoint, json=params, headers={"Authorization": os.environ.get("sec_api")})
        if response.status_code != 200:
            raise Exception(f"Form4 API error: {response.status_code} - {response.text}")
        
        data = response.json()
        with open(file_name, "w") as f:
            json.dump(data, f, indent=4)

    with open(file_name, "r") as f:
        data = json.load(f)

    for txn_filing in data.get("transactions", []):
        owner_info = txn_filing.get("reportingOwner", {})
        owner_name = owner_info.get("name", "Unknown").strip()

        if owner_name not in insider_data:
            relationship = owner_info.get("relationship", {})
            insider_data[owner_name] = {
                "is_director": relationship.get("isDirector", False),
                "is_officer": relationship.get("isOfficer", False),
                "officer_title": relationship.get("officerTitle", ""),
                "is_ten_percent_owner": relationship.get("isTenPercentOwner", False),
                "shares_bought": 0,
                "shares_sold": 0,
                "dollar_bought": 0.0,
                "dollar_sold": 0.0,
                "buy_transactions": 0,
                "sell_transactions": 0,
            }

        # Process non-derivative transactions (e.g. common stock buys/sells)
        nd_table = txn_filing.get("nonDerivativeTable", {})
        for txn in nd_table.get("transactions", []):
            code = txn.get("coding", {}).get("code", "")
            amounts = txn.get("amounts", {})
            shares = amounts.get("shares", 0) or 0
            price = amounts.get("pricePerShare", 0) or 0
            dollar_val = shares * price

            if code == "P":
                insider_data[owner_name]["shares_bought"] += shares
                insider_data[owner_name]["dollar_bought"] += dollar_val
                insider_data[owner_name]["buy_transactions"] += 1
            elif code == "S":
                insider_data[owner_name]["shares_sold"] += shares
                insider_data[owner_name]["dollar_sold"] += dollar_val
                insider_data[owner_name]["sell_transactions"] += 1

        # Process derivative transactions (e.g. options exercises)
        d_table = txn_filing.get("derivativeTable", {})
        for txn in d_table.get("transactions", []):
            code = txn.get("coding", {}).get("code", "")
            amounts = txn.get("amounts", {})
            shares = amounts.get("shares", 0) or 0
            price = amounts.get("pricePerShare", 0) or 0
            dollar_val = shares * price

            if code == "P":
                insider_data[owner_name]["shares_bought"] += shares
                insider_data[owner_name]["dollar_bought"] += dollar_val
                insider_data[owner_name]["buy_transactions"] += 1
            elif code == "S":
                insider_data[owner_name]["shares_sold"] += shares
                insider_data[owner_name]["dollar_sold"] += dollar_val
                insider_data[owner_name]["sell_transactions"] += 1

    # Compute ratios per insider
    for name, info in insider_data.items():
        total_transactions = info["buy_transactions"] + info["sell_transactions"]
        total_dollar = info["dollar_bought"] + info["dollar_sold"]

        if info["sell_transactions"] > 0:
            info["selling_ratio_transactions"] = round(info["buy_transactions"] / info["sell_transactions"], 4)
        else:
            info["selling_ratio_transactions"] = None  # no sales

        if info["dollar_sold"] > 0:
            info["selling_ratio_dollar"] = round(info["dollar_bought"] / info["dollar_sold"], 4)
        else:
            info["selling_ratio_dollar"] = None  # no sales

        info["total_transactions"] = total_transactions
        info["total_dollar"] = round(total_dollar, 2)
        info["dollar_bought"] = round(info["dollar_bought"], 2)
        info["dollar_sold"] = round(info["dollar_sold"], 2)

    return insider_data

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
    target_years = {current_year - 4, current_year - 5} # default is - 1 and -2 
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
            if filing_year in target_years and filing_year not in [f["year"] for f in state["10K"]]:
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
def enrich_with_metrics(cik, filings, ticker_s):
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
        # comupute total market equity using yfinance
        #get ticker symbol with tickers.json

        ticker = yf.Ticker(ticker_s)
        try:
            stock_info = ticker.info
            shares_outstanding = stock_info.get("sharesOutstanding")
            current_price = stock_info.get("currentPrice")
            if shares_outstanding and current_price:
                market_equity = shares_outstanding * current_price
                metrics["market_equity"] = market_equity
            else:
                metrics["market_equity"] = None
        except Exception as e:
            # print(f"Error fetching market data for CIK {cik}: {e}")
            metrics["market_equity"] = None
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
    cik, official_name, ticker_s = get_cik_from_company_name(company_name)

    if not cik:
        print("Company not found.")
        sys.exit(1)

    print(f"Found company: {official_name}")
    print(f"CIK: {cik}")
    print(f"Ticker: {ticker_s}")

    # check if json file exists
    filename = f"{ticker_s}_SEC.json"
    if os.path.exists(filename):
        print(f"Found existing file {filename}, exiting...")
        return

    filings = get_required_filings(cik)
    filings = enrich_with_metrics(cik, filings, ticker_s)
    # insiders = process_form4_insiders(ticker_s)

    output = {
        "company": official_name,
        "cik": cik,
        "ticker": ticker_s,
        "10K_latest_and_prior": [tenk for tenk in filings["10K"] if tenk["year"] in [
            max([f["year"] for f in filings["10K"]]),
            max([f["year"] for f in filings["10K"]])-1
        ]],
        "all_8K_until_1yr_back": filings["8K"],
        "Form4_this_year_only": filings["Form4"],
        # "insider_summary": insiders
    }

    filename = f"{ticker_s}_SEC.json"
    with open(filename, "w") as f:
        json.dump(output, f, indent=4)

    print(f"Saved results to {filename}")


if __name__ == "__main__":
    main()