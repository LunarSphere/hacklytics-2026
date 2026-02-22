import os
import requests
from flask import Flask, send_file, request, Response
from twilio.rest import Client
import keys

app = Flask(__name__)

ELEVEN_API_KEY = keys.ELEVEN_API_KEY
ELEVEN_VOICE_ID = keys.ELEVEN_VOICE_ID
TWILIO_ACCOUNT_SID = keys.TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN = keys.TWILIO_AUTH_TOKEN
TWILIO_PHONE_FROM = keys.TWILIO_PHONE_NUMBER  # e.g. "+15551234567" (voice-capable number)
PUBLIC_BASE_URL = keys.BASE_URL

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
AUDIO_FILE = "speech.mp3"

def generate_voice(text):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2"
    }
    response = requests.post(url, json=data, headers=headers)
    if response.status_code != 200:
        raise Exception(response.text)
    with open(AUDIO_FILE, "wb") as f:
        f.write(response.content)

@app.route("/audio")
def serve_audio():
    return send_file(AUDIO_FILE, mimetype="audio/mpeg")

# Twilio calls this URL when the call connects — it tells Twilio what to play
@app.route("/twiml", methods=["GET", "POST"])
def twiml():
    audio_url = f"{PUBLIC_BASE_URL}/audio"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Play>{audio_url}</Play>
</Response>"""
    return Response(xml, mimetype="text/xml")

@app.route("/call", methods=["POST"])
def make_call():
    phone_number = request.json.get("phone")
    message = request.json.get("message")
    generate_voice(message)
    call = client.calls.create(
        to=phone_number,
        from_=TWILIO_PHONE_FROM,
        url=f"{PUBLIC_BASE_URL}/twiml"
    )
    return {"status": "calling", "sid": call.sid}

if __name__ == "__main__":
    app.run(port=5000)