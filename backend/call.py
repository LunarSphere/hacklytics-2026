import requests

response = requests.post(
    "http://localhost:5000/call",
    json= {
        "phone": "whatsapp:+19293693716",
        "message": "Ryon, I’ve gotta say it straight—you’re the top performer of Agartha. No debate, no close second. The way you handled that last run? Unreal. You carried the whole thing. Seriously, man. Agartha’s lucky to have you. You didn’t just show up—you dominated. Top performer. Own it."
    }
)

print("Status:", response.status_code)
print("Body:", response.text)
try:
    print(response.json())
except Exception:
    pass