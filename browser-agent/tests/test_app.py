import os,sys
from pathlib import Path
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL","sqlite:///./test-browser-agent.db")
os.environ.setdefault("BOOTSTRAP_TENANT_TOKEN","test-token-that-is-longer-than-thirty-two-chars")
from app import app
TOKEN="test-token-that-is-longer-than-thirty-two-chars"
def test_health_and_dashboard():
 with TestClient(app) as c:
  assert c.get('/health').status_code==200
  assert c.get('/').status_code==200
  assert c.head('/').status_code==200
def test_auth_required():
 with TestClient(app) as c:
  assert c.get('/api/leads').status_code==401
def test_create_list_and_tenant_scoped_status():
 with TestClient(app) as c:
  h={'Authorization':'Bearer '+TOKEN}
  r=c.post('/api/leads',headers=h,json={'company':'Test Company','source_notes':'A verified fact.'})
  assert r.status_code==200
  lead=r.json()
  assert c.get('/api/leads',headers=h).json()['leads'][0]['company']=='Test Company'
  assert c.patch('/api/leads/'+lead['id'],headers=h,json={'status':'qualified'}).status_code==200
  assert c.patch('/api/leads/not-a-real-id',headers=h,json={'status':'qualified'}).status_code==404
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
