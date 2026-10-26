import os,html,secrets,hashlib,hmac,json
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request,HTTPException,Depends
from fastapi.responses import HTMLResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from sqlalchemy import create_engine,text
from sqlalchemy.exc import IntegrityError
from openai import OpenAI
from twilio.request_validator import RequestValidator

URL=os.getenv("DATABASE_URL","")
PROD=os.getenv("APP_ENV")=="production" or os.getenv("RENDER")=="true"
if URL.startswith("postgres://"): URL=URL.replace("postgres://","postgresql+psycopg://",1)
elif URL.startswith("postgresql://"): URL=URL.replace("postgresql://","postgresql+psycopg://",1)
if not URL and PROD: raise RuntimeError("DATABASE_URL required in production; refusing ephemeral storage.")
engine=create_engine(URL or "sqlite:///./voicedesk-dev.db",pool_pre_ping=True,connect_args={"check_same_thread":False} if not URL else {})
BASE=Path(__file__).parent
def init_db():
 with engine.begin() as c:
  c.execute(text("CREATE TABLE IF NOT EXISTS tenants(id TEXT PRIMARY KEY,name TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,active BOOLEAN NOT NULL DEFAULT TRUE,monthly_limit INTEGER NOT NULL DEFAULT 800,monthly_used INTEGER NOT NULL DEFAULT 0,business_faq TEXT NOT NULL DEFAULT '',phone_number TEXT UNIQUE)"))
  c.execute(text("CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL REFERENCES tenants(id),name TEXT NOT NULL,phone TEXT NOT NULL,interest TEXT NOT NULL DEFAULT '',source TEXT NOT NULL DEFAULT 'manual',status TEXT NOT NULL DEFAULT 'new',created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
  c.execute(text("CREATE TABLE IF NOT EXISTS calls(call_sid TEXT PRIMARY KEY,tenant_id TEXT NOT NULL REFERENCES tenants(id),status TEXT NOT NULL DEFAULT 'in_progress',turns INTEGER NOT NULL DEFAULT 0,history TEXT NOT NULL DEFAULT '[]')"))
  c.execute(text("CREATE TABLE IF NOT EXISTS usage_events(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL REFERENCES tenants(id),call_sid TEXT,kind TEXT NOT NULL,units INTEGER NOT NULL DEFAULT 1,created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
  tok=os.getenv("BOOTSTRAP_TENANT_TOKEN","")
  if len(tok)>=32:
   c.execute(text("INSERT INTO tenants(id,name,token_hash,monthly_limit,business_faq) VALUES('default',:n,:h,:l,:f) ON CONFLICT(id) DO NOTHING"),{"n":os.getenv("BUSINESS_NAME","Pilot Institute"),"h":hashlib.sha256(tok.encode()).hexdigest(),"l":int(os.getenv("DEFAULT_MONTHLY_MINUTES","800")),"f":os.getenv("COURSE_FAQ","Admissions will confirm fees and schedules.")})
@asynccontextmanager
async def lifespan(app):
 init_db();yield;engine.dispose()
app=FastAPI(title="VoiceDesk",version="1.0.0",docs_url=None,redoc_url=None,lifespan=lifespan)
app.mount("/static",StaticFiles(directory=str(BASE/"static")),name="static")
def digest(v): return hashlib.sha256(v.encode()).hexdigest()
def tenant_auth(req:Request):
 h=req.headers.get("authorization","")
 if not h.startswith("Bearer ") or len(h)<27: raise HTTPException(401,"Tenant bearer token required")
 with engine.begin() as c: r=c.execute(text("SELECT * FROM tenants WHERE token_hash=:h AND active=TRUE"),{"h":digest(h[7:])}).mappings().first()
 if not r: raise HTTPException(401,"Invalid or inactive tenant token")
 return dict(r)
def control_auth(req:Request):
 expected=os.getenv("CONTROL_PLANE_TOKEN",""); h=req.headers.get("authorization","")
 if len(expected)<32 or not h.startswith("Bearer ") or not hmac.compare_digest(h[7:],expected): raise HTTPException(403,"Control-plane access unavailable")
def ready(): return bool(os.getenv("OPENAI_API_KEY"))
def live(): return os.getenv("ENABLE_LIVE_CALLS","").lower()=="true"
def prompt(t): return "Receptionist for "+t["name"]+". Approved facts only: "+(t.get("business_faq") or "Admissions will confirm details.")+". Never invent fees, schedules or guarantees. If unsure offer human callback. Be concise."
def twiml(s,end=False):
 s=html.escape(s); body=f"<Response><Say>{s}</Say><Hangup/></Response>" if end else f'<Response><Gather input="speech" action="/voice/turn" method="POST" language="{html.escape(os.getenv("VOICE_LANGUAGE","en-IN"))}" speechTimeout="auto" timeout="7"><Say>{s}</Say></Gather><Say>Goodbye.</Say><Hangup/></Response>'
 return Response('<?xml version="1.0" encoding="UTF-8"?>'+body,media_type="application/xml")
async def verify_twilio(req,form):
 token=os.getenv("TWILIO_AUTH_TOKEN","")
 if not token: raise HTTPException(503,"Telephony not configured")
 url=str(req.url)
 if req.headers.get("x-forwarded-proto")=="https" and url.startswith("http://"): url="https://"+url[7:]
 if not RequestValidator(token).validate(url,dict(form),req.headers.get("X-Twilio-Signature","")): raise HTTPException(403,"Invalid provider signature")
@app.api_route("/",methods=["GET","HEAD"],response_class=HTMLResponse)
def home(): return (BASE/"static"/"index.html").read_text()
@app.get("/health")
def health(): return {"status":"ok","version":"1.0.0","database":engine.dialect.name,"ai_configured":ready(),"live_calls_enabled":live()}
@app.get("/api/status")
def status(t=Depends(tenant_auth)): return {"mode":"live" if ready() else "demo","ai_configured":ready(),"live_calls_enabled":live(),"business_name":t["name"],"language":os.getenv("VOICE_LANGUAGE","en-IN"),"telephony_configured":bool(t.get("phone_number") and os.getenv("TWILIO_AUTH_TOKEN")),"monthly_limit":t["monthly_limit"],"monthly_used":t["monthly_used"]}
class Demo(BaseModel): message:str=Field(min_length=1,max_length=500)
@app.post("/api/demo")
def demo(b:Demo,t=Depends(tenant_auth)):
 if not ready(): return {"mode":"demo","reply":"AI not configured; no AI request was made"}
 try:
  r=OpenAI(api_key=os.environ["OPENAI_API_KEY"]).chat.completions.create(model=os.getenv("OPENAI_MODEL","gpt-4o-mini"),messages=[{"role":"system","content":prompt(t)},{"role":"user","content":b.message}],temperature=.2,max_tokens=250)
  return {"mode":"live","reply":r.choices[0].message.content or ""}
 except Exception as e: raise HTTPException(502,"AI provider request failed") from e
class Lead(BaseModel):
 name:str=Field(min_length=2,max_length=100);phone:str=Field(min_length=7,max_length=32);interest:str=Field(default="",max_length=300)
@app.get("/api/leads")
def leads(t=Depends(tenant_auth)):
 with engine.begin() as c: rows=c.execute(text("SELECT id,created_at,name,phone,interest,source,status FROM leads WHERE tenant_id=:t ORDER BY created_at DESC LIMIT 100"),{"t":t["id"]}).mappings().all()
 return {"leads":[dict(x) for x in rows]}
@app.post("/api/leads")
def add_lead(b:Lead,t=Depends(tenant_auth)):
 ident=secrets.token_hex(16)
 with engine.begin() as c:
  c.execute(text("INSERT INTO leads(id,tenant_id,name,phone,interest) VALUES(:id,:t,:n,:p,:i)"),{"id":ident,"t":t["id"],"n":b.name.strip(),"p":b.phone.strip(),"i":b.interest.strip()})
  r=c.execute(text("SELECT id,created_at,name,phone,interest,source,status FROM leads WHERE id=:id AND tenant_id=:t"),{"id":ident,"t":t["id"]}).mappings().first()
 return dict(r)
class NewTenant(BaseModel):
 id:str=Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,49}$");name:str=Field(min_length=2,max_length=100);token:str=Field(min_length=32,max_length=200);monthly_limit:int=Field(default=800,ge=1,le=100000);business_faq:str=Field(default="",max_length=10000);phone_number:str=Field(default="",max_length=40)
@app.post("/control/tenants")
def new_tenant(b:NewTenant,_=Depends(control_auth)):
 try:
  with engine.begin() as c: c.execute(text("INSERT INTO tenants(id,name,token_hash,monthly_limit,business_faq,phone_number) VALUES(:id,:n,:h,:l,:f,:p)"),{"id":b.id,"n":b.name,"h":digest(b.token),"l":b.monthly_limit,"f":b.business_faq,"p":b.phone_number or None})
 except IntegrityError as e: raise HTTPException(409,"Tenant id or phone already exists") from e
 return {"id":b.id,"name":b.name,"active":True,"monthly_limit":b.monthly_limit}
@app.post("/control/tenants/{tid}/disable")
def disable(tid:str,_=Depends(control_auth)):
 with engine.begin() as c: n=c.execute(text("UPDATE tenants SET active=FALSE WHERE id=:id"),{"id":tid}).rowcount
 if not n: raise HTTPException(404,"Tenant not found")
 return {"id":tid,"active":False}
def phone_tenant(phone):
 with engine.begin() as c: r=c.execute(text("SELECT * FROM tenants WHERE phone_number=:p AND active=TRUE"),{"p":phone}).mappings().first()
 return dict(r) if r else None
@app.post("/voice")
async def voice(req:Request):
 f=await req.form();await verify_twilio(req,f)
 if not live() or not ready(): raise HTTPException(503,"Live calling disabled pending production sign-off")
 t=phone_tenant(str(f.get("To","")));sid=str(f.get("CallSid",""))
 if not t or not sid: raise HTTPException(404,"No tenant configured for this number")
 with engine.begin() as c: c.execute(text("INSERT INTO calls(call_sid,tenant_id,history) VALUES(:s,:t,'[]') ON CONFLICT(call_sid) DO NOTHING"),{"s":sid,"t":t["id"]})
 return twiml("Hello, you've reached "+t["name"]+". How can I help?")
@app.post("/voice/turn")
async def turn(req:Request):
 f=await req.form();await verify_twilio(req,f)
 if not live() or not ready(): raise HTTPException(503,"Live calling disabled")
 sid=str(f.get("CallSid",""));speech=str(f.get("SpeechResult","")).strip()[:1000]
 with engine.begin() as c: call=c.execute(text("SELECT c.*,t.name,t.business_faq,t.monthly_limit,t.monthly_used,t.active FROM calls c JOIN tenants t ON t.id=c.tenant_id WHERE c.call_sid=:s"),{"s":sid}).mappings().first()
 if not call or not call["active"]: raise HTTPException(404,"Unknown call or inactive tenant")
 if call["turns"]>=12: return twiml("Thank you. Our team will follow up. Goodbye.",True)
 if call["monthly_used"]>=call["monthly_limit"]: return twiml("Automated assistant unavailable. Please contact the team. Goodbye.",True)
 if not speech:return twiml("I didn't catch that. Could you repeat?")
 hist=json.loads(call["history"] or "[]");t={"name":call["name"],"business_faq":call["business_faq"]}
 try:
  r=OpenAI(api_key=os.environ["OPENAI_API_KEY"]).chat.completions.create(model=os.getenv("OPENAI_MODEL","gpt-4o-mini"),messages=[{"role":"system","content":prompt(t)},*hist[-10:],{"role":"user","content":speech}],temperature=.2,max_tokens=220);reply=(r.choices[0].message.content or "Our team can confirm. Goodbye.")[:1000]
 except Exception:return twiml("I cannot access that information. Please contact the team. Goodbye.",True)
 hist.extend([{"role":"user","content":speech},{"role":"assistant","content":reply}])
 with engine.begin() as c:
  n=c.execute(text("UPDATE tenants SET monthly_used=monthly_used+1 WHERE id=:t AND active=TRUE AND monthly_used<monthly_limit"),{"t":call["tenant_id"]}).rowcount
  if not n:return twiml("Automated assistant unavailable. Goodbye.",True)
  c.execute(text("UPDATE calls SET turns=turns+1,history=:h WHERE call_sid=:s AND status='in_progress'"),{"h":json.dumps(hist[-12:]),"s":sid})
  c.execute(text("INSERT INTO usage_events(id,tenant_id,call_sid,kind,units) VALUES(:id,:t,:s,'voice_turn',1)"),{"id":secrets.token_hex(16),"t":call["tenant_id"],"s":sid})
 return twiml(reply)
@app.get("/privacy",response_class=HTMLResponse)
def privacy():return "<h1>VoiceDesk privacy</h1><p>Publish a customer-specific notice and establish consent, retention, deletion and applicable privacy/telecom compliance before production use.</p>"
