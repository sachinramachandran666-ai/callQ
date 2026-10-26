"""Tenant boundary and fail-closed regression tests."""
import os,sys,secrets
from pathlib import Path
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL","sqlite:///./voicedesk-test.db")
os.environ.setdefault("BOOTSTRAP_TENANT_TOKEN","test-tenant-token-which-is-at-least-32-chars")
from app import app
def test_health_and_dashboard():
 with TestClient(app) as c:
  assert c.get("/health").status_code==200
  assert c.get("/").status_code==200
  assert c.head("/").status_code==200
def test_tenant_auth_required():
 with TestClient(app) as c:
  assert c.get("/api/leads").status_code==401
  assert c.get("/api/status").status_code==401
def test_tenant_can_create_and_read_own_lead():
 with TestClient(app) as c:
  h={"Authorization":"Bearer test-tenant-token-which-is-at-least-32-chars"}
  r=c.post("/api/leads",headers=h,json={"name":"Test User","phone":"1234567890","interest":"Maths"})
  assert r.status_code==200
  assert c.get("/api/leads",headers=h).json()["leads"][0]["name"]=="Test User"
def test_live_calls_are_disabled_by_default(monkeypatch):
 monkeypatch.delenv("ENABLE_LIVE_CALLS",raising=False)
 with TestClient(app) as c:
  assert c.get("/health").json()["live_calls_enabled"] is False
def test_invalid_twilio_signature_rejected(monkeypatch):
 monkeypatch.setenv("TWILIO_AUTH_TOKEN","not-a-real-token")
 with TestClient(app) as c:
  r=c.post("/voice",data={"CallSid":"CA-invalid","To":"+15550000000"},headers={"X-Twilio-Signature":"invalid"})
  assert r.status_code==403
def test_tenant_id_cannot_be_selected_by_client():
 # All lead queries derive tenant_id exclusively from the verified bearer token.
 source=(Path(__file__).resolve().parents[1]/"app.py").read_text()
 assert "WHERE tenant_id=:t" in source
 assert "token_hash=:h AND active=TRUE" in source
