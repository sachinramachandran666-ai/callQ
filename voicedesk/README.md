# VoiceDesk MVP

A deployable inbound voice-agent starter for Indian coaching institutes. FastAPI backend, Twilio-compatible voice webhooks, OpenAI responses, lead dashboard and manual lead capture.

## Deploy on Render
1. Connect this repository in Render.
2. Create a Web Service with runtime Docker.
3. Dockerfile path: `voicedesk/Dockerfile`; Docker context: `voicedesk`.
4. Region: Singapore; health check: `/health`.
5. Add `OPENAI_API_KEY` only after approving a spend limit. Optional: `OPENAI_MODEL` (default `gpt-4o-mini`), `BUSINESS_NAME`, `COURSE_FAQ`, `VOICE_LANGUAGE`.
6. Configure Twilio inbound voice webhook to `https://YOUR-SERVICE.onrender.com/voice` using HTTP POST. Set `TWILIO_AUTH_TOKEN` only after signature validation is implemented and tested; this MVP does not yet validate Twilio request signatures, so do not expose the voice webhook to real customer traffic until that is fixed.
7. Test `/health`, `/api/status`, and the dashboard before configuring a real phone number.

## Current MVP scope
- Desktop-first dashboard and manual lead capture
- Health/status endpoints
- OpenAI-powered text demo when an API key is configured
- Twilio-compatible inbound speech Gather webhook and multi-turn responses
- Approved-facts system prompt to reduce invented business information

## Not production-ready yet
- No authentication or tenant isolation on the dashboard/API
- SQLite defaults to `/tmp`, which is ephemeral on Render; leads may be lost on restart
- In-memory call sessions are not durable and do not work reliably across multiple instances
- Twilio request signatures are not validated
- No billing, usage enforcement, recording management, consent logging or retention automation
- Live calling requires a Twilio account/number and paid voice/API usage

Do not use for real customer calls until the security, persistence, consent and cost controls above are addressed.
