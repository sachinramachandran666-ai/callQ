import os, secrets, hashlib, json
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from openai import OpenAI

URL=os.getenv("DATABASE_URL","")
PROD=os.getenv("APP_ENV")=="production"
if URL.startswith("postgres://"): URL=URL.replace("postgres://","postgresql+psycopg://",1)
elif URL.startswith("postgresql://"): URL=URL.replace("postgresql://","postgresql+psycopg://",1)
if PROD and not URL: raise RuntimeError("DATABASE_URL required in production; refusing ephemeral storage")
engine=create_engine(URL or "sqlite:///./browser-agent-dev.db",pool_pre_ping=True,connect_args={"check_same_thread":False} if not URL else {})
BASE=Path(__file__).parent
def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def init_db():
 with engine.begin() as c:
  c.execute(text("CREATE TABLE IF NOT EXISTS tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, active BOOLEAN NOT NULL DEFAULT TRUE)"))
  c.execute(text("CREATE TABLE IF NOT EXISTS leads (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), company TEXT NOT NULL, website TEXT NOT NULL DEFAULT '', contact_name TEXT NOT NULL DEFAULT '', contact_email TEXT NOT NULL DEFAULT '', source_notes TEXT NOT NULL DEFAULT '', research_brief TEXT NOT NULL DEFAULT '', outreach_draft TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new', created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
  token=os.getenv("BOOTSTRAP_TENANT_TOKEN","")
  if len(token)>=32:
   # Upsert so rotating the configured bootstrap secret actually invalidates the old token.
   c.execute(text("INSERT INTO tenants(id,name,token_hash) VALUES('default',:n,:h) ON CONFLICT(id) DO UPDATE SET name=excluded.name, token_hash=excluded.token_hash, active=TRUE"),{"n":os.getenv("BUSINESS_NAME","LeadPilot Workspace"),"h":digest(token)})
@asynccontextmanager
async def lifespan(app):
 init_db(); yield; engine.dispose()
app=FastAPI(title="LeadPilot",version="0.1.0",docs_url=None,redoc_url=None,lifespan=lifespan)
app.mount("/static",StaticFiles(directory=str(BASE/"static")),name="static")
@app.middleware("http")
async def security_and_size_middleware(request:Request, call_next):
 length=request.headers.get("content-length")
 if length:
  try:
   if int(length)>1024*1024:
    return JSONResponse(status_code=413,content={"detail":"Request body too large"})
  except ValueError:
   return JSONResponse(status_code=400,content={"detail":"Invalid Content-Length"})
 response=await call_next(request)
 response.headers["X-Content-Type-Options"]="nosniff"
 response.headers["X-Frame-Options"]="DENY"
 response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
 response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
 if request.url.path.startswith("/api/"): response.headers["Cache-Control"]="no-store"
 return response
def tenant_auth(req:Request):
 h=req.headers.get("authorization","")
 if not h.startswith("Bearer ") or len(h[7:])<32: raise HTTPException(401,"Workspace token required")
 with engine.begin() as c: row=c.execute(text("SELECT id,name FROM tenants WHERE token_hash=:h AND active=TRUE"),{"h":digest(h[7:])}).mappings().first()
 if not row: raise HTTPException(401,"Invalid or inactive workspace token")
 return dict(row)
@app.api_route("/",methods=["GET","HEAD"],response_class=HTMLResponse)
def home(): return (BASE/"static"/"index.html").read_text()
@app.get("/health")
def health(): return {"status":"ok","database":engine.dialect.name,"ai_configured":bool(os.getenv("OPENAI_API_KEY"))}
@app.get("/readyz")
def readiness():
 try:
  with engine.connect() as c: c.execute(text("SELECT 1"))
  return {"status":"ready","database":"reachable"}
 except Exception:
  raise HTTPException(503,"Database is not ready")
class LeadIn(BaseModel):
 company:str=Field(min_length=2,max_length=160)
 website:str=Field(default="",max_length=500)
 contact_name:str=Field(default="",max_length=120)
 contact_email:str=Field(default="",max_length=254)
 source_notes:str=Field(default="",max_length=12000)
class LeadUpdate(BaseModel):
 status:str=Field(pattern="^(new|researching|contacted|qualified|not_a_fit|won|lost)$")
@app.get("/api/leads")
def list_leads(t=Depends(tenant_auth)):
 with engine.begin() as c: rows=c.execute(text("SELECT id,company,website,contact_name,contact_email,source_notes,research_brief,outreach_draft,status,created_at,updated_at FROM leads WHERE tenant_id=:t ORDER BY updated_at DESC LIMIT 300"),{"t":t["id"]}).mappings().all()
 return {"leads":[dict(r) for r in rows]}
@app.post("/api/leads")
def create_lead(b:LeadIn,t=Depends(tenant_auth)):
 if b.website and not (b.website.startswith("https://") or b.website.startswith("http://")): raise HTTPException(422,"Website must start with http:// or https://")
 ident=secrets.token_hex(16)
 with engine.begin() as c:
  c.execute(text("INSERT INTO leads(id,tenant_id,company,website,contact_name,contact_email,source_notes) VALUES(:id,:t,:c,:w,:n,:e,:s)"),{"id":ident,"t":t["id"],"c":b.company.strip(),"w":b.website.strip(),"n":b.contact_name.strip(),"e":b.contact_email.strip(),"s":b.source_notes.strip()})
  row=c.execute(text("SELECT id,company,website,contact_name,contact_email,source_notes,research_brief,outreach_draft,status,created_at,updated_at FROM leads WHERE id=:id AND tenant_id=:t"),{"id":ident,"t":t["id"]}).mappings().first()
 return dict(row)
@app.patch("/api/leads/{lead_id}")
def update_lead(lead_id:str,b:LeadUpdate,t=Depends(tenant_auth)):
 with engine.begin() as c: n=c.execute(text("UPDATE leads SET status=:s,updated_at=CURRENT_TIMESTAMP WHERE id=:id AND tenant_id=:t"),{"s":b.status,"id":lead_id,"t":t["id"]}).rowcount
 if not n: raise HTTPException(404,"Lead not found")
 return {"id":lead_id,"status":b.status}
class DraftRequest(BaseModel):
 task:str=Field(default="research_and_outreach",pattern="^(research_and_outreach|outreach_only|research_only)$")
@app.post("/api/leads/{lead_id}/draft")
def draft(lead_id:str,b:DraftRequest,t=Depends(tenant_auth)):
 if not os.getenv("OPENAI_API_KEY"): raise HTTPException(503,"AI drafting is not configured. No generated or demo result was returned.")
 with engine.begin() as c: lead=c.execute(text("SELECT * FROM leads WHERE id=:id AND tenant_id=:t"),{"id":lead_id,"t":t["id"]}).mappings().first()
 if not lead: raise HTTPException(404,"Lead not found")
 ask={"company":lead["company"],"website":lead["website"],"contact_name":lead["contact_name"],"contact_email":lead["contact_email"],"user_supplied_notes":lead["source_notes"],"task":b.task}
 sys="You are a careful B2B prospect research assistant. Use only supplied facts. Never claim you visited a website or independently verified information. Mark missing facts as unknown. Do not invent people, emails, prices, company facts, or personal details. Return concise JSON with keys research_brief and outreach_draft. Draft outreach should be relevant, transparent, and non-deceptive. If notes are empty, state that more source information is required and keep outreach generic."
 try:
  result=OpenAI(api_key=os.environ["OPENAI_API_KEY"]).chat.completions.create(model=os.getenv("OPENAI_MODEL","gpt-4o-mini"),messages=[{"role":"system","content":sys},{"role":"user","content":json.dumps(ask)}],response_format={"type":"json_object"},temperature=.2,max_tokens=900)
  data=json.loads(result.choices[0].message.content or "{}")
  brief=str(data.get("research_brief",""))[:6000]; outreach=str(data.get("outreach_draft",""))[:6000]
 except Exception as e: raise HTTPException(502,"AI provider failed; no draft was saved") from e
 with engine.begin() as c: c.execute(text("UPDATE leads SET research_brief=:r,outreach_draft=:o,status=CASE WHEN status='new' THEN 'researching' ELSE status END,updated_at=CURRENT_TIMESTAMP WHERE id=:id AND tenant_id=:t"),{"r":brief,"o":outreach,"id":lead_id,"t":t["id"]})
 return {"id":lead_id,"research_brief":brief,"outreach_draft":outreach,"mode":"live_ai"}
@app.get("/privacy",response_class=HTMLResponse)
def privacy(): return "<h1>Privacy notice placeholder</h1><p>Before customer launch, publish a reviewed privacy notice, define retention/deletion, and complete applicable privacy compliance.</p>"
