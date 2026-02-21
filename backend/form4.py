import keys
import requests
import json
endpoint = "https://api.sec-api.io/insider-trading"
params = {
    "query": "issuer.tradingSymbol:TSLA",
    "from": "0",
    "size": "50",
    "sort": [{ "filedAt": { "order": "desc" } }]
}

response = requests.post(endpoint, json=params, headers={"Authorization": keys.FORM4_API_KEY})
if response.status_code == 200:
    data = response.json()
    print(json.dumps(data, indent=4))
    with open("form4_data.json", "w") as f:
        json.dump(data, f, indent=4)