"""
telephony/twilio_adapter.py

Thin phone adapter: the same LenaAgent that powers evals and the terminal
demo, delivered over a Twilio call. Deliberately isolated -- swapping this
file for a SIP/Amazon Connect/LiveKit adapter changes nothing else, which
mirrors how production voice platforms stay telephony-agnostic.

Pre-dial compliance lives HERE (code, not prompt): opted-out numbers are
refused before the phone ever rings.

Run:  uvicorn telephony.twilio_adapter:app --port 8000
Env:  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER,
      PUBLIC_BASE_URL, ANTHROPIC_API_KEY
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import VoiceResponse, Gather

load_dotenv()

from agent.core import LenaAgent          # noqa: E402
from supervisor.qa import QASupervisor       # noqa: E402
from supervisor.summary import LeasingSummary  # noqa: E402
from notifications.sms import send_booking_confirmations  # noqa: E402
from telephony.dashboard import router as dashboard_router  # noqa: E402
from db.database import Database             # noqa: E402

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
VOICE = "Polly.Joanna-Neural"

app = FastAPI(title="Lena phone adapter")
db = Database()
sessions: dict[str, LenaAgent] = {}


def _twiml(text: str, listen: bool) -> Response:
    vr = VoiceResponse()
    if listen:
        g = Gather(input="speech", action=f"{PUBLIC_BASE_URL}/respond",
                   method="POST", speech_timeout="auto", language="en-US")
        g.say(text, voice=VOICE)
        vr.append(g)
        vr.say("Sorry, I didn't catch that. Goodbye!", voice=VOICE)
        vr.hangup()
    else:
        vr.say(text, voice=VOICE)
        vr.hangup()
    return Response(content=str(vr), media_type="application/xml")


@app.post("/start-call")
async def start_call(request: Request):
    body = await request.json()
    to_number = body["to"]

    # -------- pre-dial compliance gate: enforced in code, before dialing
    if db.is_opted_out(to_number):
        return {"status": "refused", "reason": "number has opted out"}

    twilio = TwilioClient(os.environ["TWILIO_ACCOUNT_SID"],
                          os.environ["TWILIO_AUTH_TOKEN"])
    call = twilio.calls.create(
        to=to_number,
        from_=os.environ["TWILIO_FROM_NUMBER"],
        url=f"{PUBLIC_BASE_URL}/voice",
        status_callback=f"{PUBLIC_BASE_URL}/call-status",
        status_callback_event=["completed"],
    )
    return {"status": "calling", "call_sid": call.sid}


@app.post("/voice")
async def voice(CallSid: str = Form(...)):
    agent = LenaAgent(db=db)
    sessions[CallSid] = agent
    return _twiml(agent.greet(), listen=True)


@app.post("/respond")
async def respond(CallSid: str = Form(...), SpeechResult: str = Form(default="")):
    agent = sessions.get(CallSid)
    if agent is None:
        return _twiml("Sorry, something went wrong. Goodbye.", listen=False)
    reply = agent.respond(SpeechResult.strip() or "(silence)")
    return _twiml(reply, listen=not agent.ended)


@app.post("/call-status")
async def call_status(CallSid: str = Form(...), CallStatus: str = Form(...)):
    agent = sessions.pop(CallSid, None)
    if agent and CallStatus == "completed":
        scorecard = QASupervisor().grade(agent)
        summary = LeasingSummary().generate(agent.transcript)
        agent.finalize(qa_scorecard=scorecard, summary=summary)
        send_booking_confirmations(agent)
    return {"ok": True}


app.include_router(dashboard_router)
