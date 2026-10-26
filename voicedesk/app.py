import os, json, sqlite3, time, html, secrets
from contextlib import closing
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from openai import OpenAI
from twilio.request_validator import RequestValidator

APP_DIR = Path(__file__).parent
DB_PATH = os.getenv("DB_PATH", "/tmp/voicedesk.db")
app = FastAPI(title="VoiceDesk", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
sessions = {}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        name TEXT, phone TEXT, interest TEXT, source TEXT DEFAULT 'voice', status TEXT DEFAULT 'new'
    )""")
    return conn

def configured():
    return bool(os.getenv("OPENAI_API_KEY"))

def require_admin(request: Request):
    expected = os.getenv("ADMIN_TOKEN", "")
    supplied = request.headers.get("authorization", "")
    if not expected:
        raise HTTPException(503, "Set ADMIN_TOKEN in Render environment variables before enabling lead access.")
    if not supplied.startswith("Bearer ") or not secrets.compare_digest(supplied[7:], expected):
        raise HTTPException(401, "Admin token required.")

async def validate_twilio(request: Request, form):
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not token:
        raise HTTPException(503, "Inbound calling is disabled until TWILIO_AUTH_TOKEN is configured.")
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    if request.headers.get("x-forwarded-proto") == "https" and url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    if not RequestValidator(token).validate(url, dict(form), signature):
        raise HTTPException(403, "Invalid telephony provider signature.")

def twiml_gather(prompt="Hello, you've reached the admissions assistant. How can I help you today?"):
    safe = html.escape(prompt)
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response><Gather input="speech" action="/voice/turn" method="POST" language="{html.escape(os.getenv("VOICE_LANGUAGE","en-IN"))}" speechTimeout="auto" timeout="7"><Say>{safe}</Say></Gather><Say>Sorry, I didn't hear anything. Please call again.</Say><Hangup/></Response>'''
    return Response(content=xml, media_type="application/xml")

@app.get("/", response_class=HTMLResponse)
def home():
    return (APP_DIR / "static" / "index.html").read_text(encoding="utf-8")

@app.get("/health")
def health():
    return {"status":"ok","app":"voicedesk","version":"0.1.0","ai_configured":configured(),"mode":"live" if configured() else "demo"}

@app.get("/api/status")
def status():
    return {"mode":"live" if configured() else "demo","ai_configured":configured(),
      "business_name":os.getenv("BUSINESS_NAME","Demo Coaching Institute"),
      "language":os.getenv("VOICE_LANGUAGE","en-IN"),
      "telephony_configured":bool(os.getenv("TWILIO_AUTH_TOKEN")),
      "storage":"local SQLite (ephemeral on default Render filesystem); configure persistent storage before production"}

class DemoMessage(BaseModel):
    message: str

@app.post("/api/demo")
def demo(body: DemoMessage):
    if not body.message.strip():
        raise HTTPException(400,"Message cannot be empty")
    if not configured():
        return {"mode":"demo","reply":"Demo mode is active. Add OPENAI_API_KEY to enable live AI responses. Your message was not sent to an AI provider.","lead":None}
    try:
        client=OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        completion=client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL","gpt-4o-mini"),
            messages=[
              {"role":"system","content":system_prompt()},
              {"role":"user","content":body.message}
            ], temperature=0.2)
        return {"mode":"live","reply":completion.choices[0].message.content or ""}
    except Exception as e:
        raise HTTPException(502,"AI provider request failed; check server logs and API configuration.") from e

def system_prompt():
    business=os.getenv("BUSINESS_NAME","Demo Coaching Institute")
    courses=os.getenv("COURSE_FAQ","We offer online and classroom coaching. Fees and schedules are confirmed by the admissions team.")
    return ("You are the inbound phone receptionist for "+business+". Be concise, polite, and clear. "
      "Only use these approved business facts: "+courses+" Never invent fees, discounts, guarantees, eligibility, or schedules. "
      "If unsure, say the admissions team will confirm and offer a callback. Ask one question at a time. "
      "Collect a caller's name, phone number and course interest only when relevant. Do not request sensitive personal data.")

@app.post("/voice")
async def voice(request: Request):
    form = await request.form()
    await validate_twilio(request, form)
    if not configured():
        return twiml_gather("This VoiceDesk demo is not connected to its AI service yet. Please configure the service before accepting customer calls.")
    call_sid = str(form.get("CallSid",""))
    sessions[call_sid] = []
    return twiml_gather()

@app.post("/voice/turn")
async def voice_turn(request: Request):
    form = await request.form()
    await validate_twilio(request, form)
    call_sid = str(form.get("CallSid","unknown"))
    speech = str(form.get("SpeechResult","")).strip()
    if not speech:
        return twiml_gather("I didn't catch that. Could you please repeat?")
    if not configured():
        return twiml_gather("The AI service is not configured yet. Please call back later.")
    history = sessions.setdefault(call_sid, [])
    history.append({"role":"user","content":speech})
    try:
        client=OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        completion=client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL","gpt-4o-mini"),
            messages=[{"role":"system","content":system_prompt()},*history[-12:]],
            temperature=0.2)
        reply=(completion.choices[0].message.content or "I can arrange for the admissions team to call you back.").strip()
        history.append({"role":"assistant","content":reply})
        if len(history)>16: sessions[call_sid]=history[-16:]
        return twiml_gather(reply)
    except Exception:
        return twiml_gather("I'm having trouble accessing the admissions information. I can arrange a callback. Please try again later.")

@app.get("/api/leads")
def get_leads(request: Request):
    require_admin(request)
    with closing(db()) as conn:
        rows=conn.execute("SELECT id,created_at,name,phone,interest,source,status FROM leads ORDER BY id DESC LIMIT 100").fetchall()
        return {"leads":[dict(row) for row in rows]}

class LeadIn(BaseModel):
    name: str
    phone: str
    interest: str = ""

@app.post("/api/leads")
def create_lead(lead: LeadIn, request: Request):
    require_admin(request)
    if len(lead.name.strip()) < 2 or len(lead.phone.strip()) < 7:
        raise HTTPException(400,"Enter a valid name and phone number")
    with closing(db()) as conn:
        cur=conn.execute("INSERT INTO leads(name,phone,interest) VALUES(?,?,?)",
          (lead.name.strip()[:100],lead.phone.strip()[:32],lead.interest.strip()[:300]))
        conn.commit()
        row=conn.execute("SELECT id,created_at,name,phone,interest,source,status FROM leads WHERE id=?",(cur.lastrowid,)).fetchone()
        return dict(row)

@app.patch("/api/leads/{lead_id}")
def update_lead(lead_id: int, request: Request):
    raise HTTPException(501,"Lead status editing will be enabled after authentication is added.")

@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return """<h1>VoiceDesk privacy notice</h1><p>This MVP should only be used with appropriate notice and consent. Do not submit sensitive personal data. The demo lead form stores details in a local SQLite database that may be lost when the hosting instance restarts. Configure persistent encrypted storage, access controls, a retention policy and required notices before production use.</p>"""

