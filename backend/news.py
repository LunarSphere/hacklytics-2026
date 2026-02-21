import requests
import keys
import json  # for writing JSON to a file

URL = "https://newsapi.org/v2/everything"
params = {
    "q": "apple",
    "from": "2026-01-21", 
    "sortBy": "publishedAt",
    "pageSize": 10, 
    "apiKey": keys.NEWS_API_KEY
}

# Fetch data
response = requests.get(URL, params=params)
data = response.json()

# Print JSON to console (optional)
print(data)

# Write JSON to a file
with open("apple_news.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=4)

print("Saved news JSON to apple_news.json")