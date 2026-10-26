import os,sys
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import text
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL","sqlite:///./test-browser-agent.db")
os.environ.setdefault("BOOTSTRAP_TENANT_TOKEN","test-token-that-is-longer-than-thirty-two-chars")
from app import app, engine, digest
TOKEN="test-token-that-is-longer-than-thirty-two-chars"
OTHER_TOKEN="other-workspace-token-that-is-over-thirty-two-chars"
def ensure_other_tenant():
 with engine.begin() as c:
  c.execute(text("INSERT INTO tenants(id,name,token_hash,active) VALUES(:id,:name,:hash,TRUE) ON CONFLICT(id) DO UPDATE SET token_hash=excluded.token_hash,active=TRUE"),{"id":"other-test","name":"Other test workspace","hash":digest(OTHER_TOKEN)})
def test_health_and_dashboard():
 with TestClient(app) as c:
  assert c.get('/health').status_code==200
  assert c.get('/readyz').status_code==200
  assert c.get('/health').headers['x-content-type-options']=='nosniff'
  assert c.get('/health').headers['x-frame-options']=='DENY'
  assert c.get('/').status_code==200
  assert c.head('/').status_code==200
def test_auth_required():
 with TestClient(app) as c:
  assert c.get('/api/leads').status_code==401
def test_create_list_and_tenant_scoped_status():
 ensure_other_tenant()
 with TestClient(app) as c:
  h={'Authorization':'Bearer '+TOKEN}
  r=c.post('/api/leads',headers=h,json={'company':'Test Company','source_notes':'A verified fact.'})
  assert r.status_code==200
  lead=r.json()
  assert c.get('/api/leads',headers=h).json()['leads'][0]['company']=='Test Company'
  assert c.patch('/api/leads/'+lead['id'],headers=h,json={'status':'qualified'}).status_code==200
  other={'Authorization':'Bearer '+OTHER_TOKEN}
  assert c.get('/api/leads',headers=other).json()['leads']==[]
  assert c.patch('/api/leads/'+lead['id'],headers=other,json={'status':'lost'}).status_code==404
def test_ai_fails_closed_without_key(monkeypatch):
 monkeypatch.delenv('OPENAI_API_KEY',raising=False)
 with TestClient(app) as c:
  h={'Authorization':'Bearer '+TOKEN}
  r=c.post('/api/leads',headers=h,json={'company':'AI Test Co','source_notes':'Some source text'})
  assert r.status_code==200
  assert c.post('/api/leads/'+r.json()['id']+'/draft',headers=h,json={}).status_code==503
def test_client_cannot_choose_tenant():
 source=(Path(__file__).resolve().parents[1]/'app.py').read_text()
 assert 'WHERE tenant_id=:t' in source
 assert 'token_hash=:h AND active=TRUE' in source
def test_bootstrap_token_rotation_updates_existing_workspace():
 with TestClient(app) as c:
  old={'Authorization':'Bearer '+TOKEN}
  assert c.get('/api/leads',headers=old).status_code==200
  import app as app_module
  os.environ["BOOTSTRAP_TENANT_TOKEN"]="rotated-token-that-is-longer-than-thirty-two-characters"
  app_module.init_db()
  assert c.get('/api/leads',headers=old).status_code==401
  assert c.get('/api/leads',headers={'Authorization':'Bearer '+os.environ["BOOTSTRAP_TENANT_TOKEN"]}).status_code==200
  os.environ["BOOTSTRAP_TENANT_TOKEN"]=TOKEN
  app_module.init_db()

def test_oversized_request_rejected():
 with TestClient(app) as c:
  r=c.post('/api/leads',headers={'Content-Length':str(2*1024*1024)})
  assert r.status_code==413
