# VoiceDesk MVP

A deployable inbound voice-agent starter for Indian coaching institutes. FastAPI backend, Twilio-compatible voice webhooks, OpenAI responses, lead dashboard and manual lead capture.

## Deploy on Render
1. Connect this repository in Render.
2. Create a Web Service with runtime Docker.
3. Dockerfile path: `voicedesk/Dockerfile`; Docker context: `voicedesk`.
4. Region: Singapore; health check: `/health`.
5. Set a strong, unique `ADMIN_TOKEN` in Render before using the lead inbox. Add `OPENAI_API_KEY` only after approving a spend limit. Optional: `OPENAI_MODEL` (default `gpt-4o-mini`), `BUSINESS_NAME`, `COURSE_FAQ`, `VOICE_LANGUAGE`.
6. Configure `TWILIO_AUTH_TOKEN` in Render and set the Twilio inbound voice webhook to `https://YOUR-SERVICE.onrender.com/voice` using HTTP POST. The MVP validates Twilio request signatures, but the complete call flow still requires end-to-end testing before real customer traffic.
7. Test `/health`, `/api/status`, and the dashboard before configuring a real phone number.

## Current MVP scope
- Desktop-first dashboard and manual lead capture
- Health/status endpoints
- OpenAI-powered text demo when an API key is configured
- Twilio-compatible inbound speech Gather webhook and multi-turn responses
- Approved-facts system prompt to reduce invented business information

## Not production-ready yet
- Lead endpoints require a bearer token via `ADMIN_TOKEN`; the single-tenant MVP does not yet provide per-customer tenant isolation
- SQLite defaults to `/tmp`, which is ephemeral on Render; leads may be lost on restart
- In-memory call sessions are not durable and do not work reliably across multiple instances
- Telephony provider configuration and signature validation need end-to-end testing against the configured public URL
- No billing, usage enforcement, recording management, consent logging or retention automation
- Live calling requires a Twilio account/number and paid voice/API usage

Do not use for real customer calls until the security, persistence, consent and cost controls above are addressed.

## Production release gate (not yet passed)
- [x] Public dashboard and container build
- [x] Admin-token gate for lead endpoints and AI text demo
- [x] Twilio request-signature check
- [x] Live calling disabled unless ENABLE_LIVE_CALLS=true
- [x] Maximum call turns; basic regression tests added (execution not yet verified)
- [ ] Durable encrypted database, backups, restore test and retention deletion
- [ ] Multi-tenant isolation with per-tenant RBAC and automated negative tests
- [ ] Per-tenant usage quotas, billing and hard spending caps
- [ ] Call-state persistence, idempotency and concurrency/load tests
- [ ] Consent and legal/privacy review for recording, retention and outbound communications
- [ ] End-to-end Twilio live-call validation and AI quality evaluation
- [ ] Verified CI test run, monitoring, alerts and incident runbook

Do not set ENABLE_LIVE_CALLS=true or accept real customer data until every mandatory gate passes.
