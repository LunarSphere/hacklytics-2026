import requests
import json
from datetime import datetime, timedelta
import sys
import os

HEADERS = {
    "User-Agent": "YourName your.email@example.com",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov"
}

LOCAL_TICKERS_FILE = "tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
BASE_URL = "https://data.sec.gov/submissions/"


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

            # Check if at least one 8-K is >= 1 year old
            if filing_date <= one_year_ago:
                state["found_old_8k"] = True

        # ---- Form 4 (this year only) ----
        elif form == "4" and filing_year == current_year:
            state["Form4"].append(filing_entry)

    return state


def requirements_met(state):
    return (
        len(state["10K"]) >= 2 and
        state["found_old_8k"]
    )


def get_required_filings(cik):
    state = {
        "10K": [],
        "8K": [],
        "Form4": [],
        "found_old_8k": False
    }

    # 1️⃣ Main submissions file
    main_json = fetch_json(SUBMISSIONS_URL.format(cik=cik))
    state = process_block(main_json, state)

    # 2️⃣ Fetch older files only if needed
    if not requirements_met(state):
        older_files = main_json.get("filings", {}).get("files", [])

        for file_info in older_files:
            older_json = fetch_json(BASE_URL + file_info["name"])
            state = process_block(older_json, state)

            if requirements_met(state):
                break

    # Sort and keep only 2 most recent 10Ks
    state["10K"] = sorted(
        state["10K"],
        key=lambda x: x["filing_date"],
        reverse=True
    )[:2]

    # Sort 8Ks newest first
    state["8K"] = sorted(
        state["8K"],
        key=lambda x: x["filing_date"],
        reverse=True
    )

    return state


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

    output = {
        "company": official_name,
        "cik": cik,
        "two_most_recent_10K": filings["10K"],
        "all_8K_until_1yr_back": filings["8K"],
        "Form4_this_year_only": filings["Form4"]
    }

    filename = f"{official_name.replace(' ', '_')}_SEC_combined.json"

    with open(filename, "w") as f:
        json.dump(output, f, indent=4)

    print(f"Saved results to {filename}")


if __name__ == "__main__":
    main()