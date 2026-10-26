# VoiceDesk

VoiceDesk is an inbound voice-agent pilot for coaching institutes. It has a desktop dashboard, tenant-scoped lead APIs, PostgreSQL support, OpenAI response generation, Twilio signature validation, usage counters, and a fail-closed live-calling switch.

## Current status

**Pilot deployed; not approved for production customer data.** The current Render service has no dedicated VoiceDesk PostgreSQL database configured. It therefore runs in local SQLite fallback mode, which is not durable on Render. Live calls are explicitly disabled.

## Required production configuration

Set these on the Render web service:
- `DATABASE_URL`: dedicated PostgreSQL connection string for VoiceDesk. Use a private/internal connection where possible and TLS as required by the provider.
- `APP_ENV=production`: makes the application refuse to start if `DATABASE_URL` is absent.
- `BOOTSTRAP_TENANT_TOKEN`: unique random token, minimum 32 characters, for the initial tenant. Never commit it.
- `CONTROL_PLANE_TOKEN`: separate unique random token, minimum 32 characters, for tenant provisioning and disabling.
- `OPENAI_API_KEY`: only after setting provider spend limits.
- `TWILIO_AUTH_TOKEN`: only when the inbound number and webhook have been configured.
- `ENABLE_LIVE_CALLS=false` until end-to-end validation and the release gate passes.

Optional: `OPENAI_MODEL` (default `gpt-4o-mini`), `BUSINESS_NAME`, `COURSE_FAQ`, `VOICE_LANGUAGE`, `DEFAULT_MONTHLY_MINUTES`.

## Deploy

Render service: https://dashboard.render.com/web/srv-dbfsptm1egvs73c6s4s0
Repository path: `voicedesk/`
Dockerfile: `voicedesk/Dockerfile`
Health endpoint: `/health`

The service auto-deploys on commits to `main`. The GitHub Actions workflow `.github/workflows/voicedesk-ci.yml` runs regression tests when enabled. Confirm the run result before releasing.

## Tenant management

All `/api/*` endpoints require a tenant bearer token. Tenant tokens are stored as SHA-256 hashes; the raw token is not stored in the database. Each lead query is scoped to the authenticated tenant.

Create a tenant using the control-plane token:
```bash
curl -X POST https://YOUR-SERVICE/control/tenants \
  -H "Authorization: Bearer $CONTROL_PLANE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"id":"institute-a","name":"Institute A","token":"REPLACE_WITH_A_UNIQUE_RANDOM_TOKEN_32_CHARS_MIN","monthly_limit":800,"business_faq":"Approved course information only","phone_number":"+91XXXXXXXXXX"}'
```

Disable a tenant:
```bash
curl -X POST https://YOUR-SERVICE/control/tenants/institute-a/disable \
  -H "Authorization: Bearer $CONTROL_PLANE_TOKEN"
```

Configure the Twilio inbound voice webhook to `https://YOUR-SERVICE/voice` with HTTP POST. The phone number's `To` value must exactly match the active tenant's configured `phone_number`. Test the public webhook signature against the real provider before enabling live calling.

## Implemented controls

- Tenant-scoped lead reads and writes.
- Hashed tenant tokens and separate control-plane authentication.
- Unique tenant phone-number mapping.
- Twilio signature validation.
- Live calling disabled unless explicitly enabled.
- Call-turn ceiling and tenant usage counter/limit.
- Approved-facts prompt; errors fail closed instead of returning canned analysis as live AI.
- Basic automated tests for tenant auth and isolation.

## Release blockers — do not skip

- Dedicated durable PostgreSQL database, backup and restore drill.
- Fix monthly usage accounting to be calendar-period based and minute-based; current counter is a coarse turn counter, not billing-grade usage.
- Make call-turn/quota updates transactional and idempotent under concurrent webhooks.
- Add rate limiting, webhook replay/idempotency controls and stricter request-size limits.
- Replace token-based shared tenant access with per-user RBAC and token rotation/revocation.
- Add tenant-aware lead creation from call conversations; the current voice flow does not automatically extract and persist leads.
- Add call-session expiry and retention/deletion jobs.
- Verify all SQL and tests on PostgreSQL, run cross-tenant negative tests, load tests and restore tests.
- Add observability, alerting, incident runbook, cost alarms and hard provider spend limits.
- Complete privacy, consent, retention and telecom compliance review.
- Perform end-to-end test calls with a test number before real customer traffic.

**Do not set `APP_ENV=production` without `DATABASE_URL`. Do not set `ENABLE_LIVE_CALLS=true` until all release blockers are resolved.**
