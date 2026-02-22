from flask import Flask, request, jsonify
from flask_cors import CORS
import traceback

import quant_tool

app = Flask(__name__)
CORS(app)


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    POST /analyze
    Body: { "company": "Apple Inc." }

    Returns the full fraud-risk metrics JSON for the given company.
    """
    body = request.get_json(silent=True) or {}
    company_name = body.get("company", "").strip()

    if not company_name:
        return jsonify({"error": "Missing 'company' field in request body."}), 400

    try:
        ticker, results = quant_tool.run_pipeline(company_name)
    except SystemExit:
        return jsonify({"error": f"Company '{company_name}' not found."}), 404
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "ticker": ticker,
        "company": company_name,
        "m_score": results["m_score"],
        "z_score": results["z_score"],
        "accruals_ratio": results["accruals_ratio"],
        "short_interest": results["short_interest"],
        "insider_trading": results["insider_trading"],
        "composite_fraud_risk_score": results["composite_fraud_risk_score"],
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
