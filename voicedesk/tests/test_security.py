"""Security regression tests for the VoiceDesk pilot. Run: pip install pytest httpx && pytest voicedesk/tests"""
import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app

client = TestClient(app)

def test_health_and_dashboard():
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.head("/").status_code == 200

def test_leads_fail_closed_without_token(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert client.get("/api/leads").status_code == 503
    assert client.post("/api/leads", json={"name":"Test","phone":"1234567890"}).status_code == 503

def test_admin_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-secret")
    assert client.get("/api/leads", headers={"Authorization":"Bearer wrong"}).status_code == 401

def test_demo_requires_auth(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-secret")
    assert client.post("/api/demo", json={"message":"Hello"}).status_code == 401
    assert client.post("/api/demo", json={"message":"x"*501}, headers={"Authorization":"Bearer test-secret"}).status_code == 413

def test_twilio_requires_config(monkeypatch):
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    assert client.post("/voice", data={"CallSid":"CA123"}).status_code == 503
    assert client.post("/voice/turn", data={"CallSid":"CA123","SpeechResult":"Hello"}).status_code == 503

def test_invalid_twilio_signature(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "fake-token")
    assert client.post("/voice", data={"CallSid":"CA123"}, headers={"X-Twilio-Signature":"invalid"}).status_code == 403

def test_live_calls_off_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_LIVE_CALLS", raising=False)
    assert client.get("/api/status").json()["live_calls_enabled"] is False
