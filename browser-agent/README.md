# LeadPilot — browser-based business workflow agent

A desktop-first B2B prospect workspace: capture a lead, store source notes, track pipeline status, and generate a research brief/outreach draft from supplied information.

## Important scope limits
- This MVP does **not** browse websites, verify facts, send email, or execute unattended browser actions. Website research facts must be supplied by the operator.
- AI generation is real-provider-only. Without `OPENAI_API_KEY`, drafting returns HTTP 503; it never returns canned/demo output.
- API requests require a workspace bearer token. Tenant IDs are derived from the authenticated token; clients cannot select another tenant's records.
- Production startup refuses to run without `APP_ENV=production` and `DATABASE_URL` configured. SQLite is local development/test only.

## Run locally

```bash
cd browser-agent
python -m venv .venv
pip install -r requirements.txt
export BOOTSTRAP_TENANT_TOKEN='replace-with-a-random-secret-of-at-least-32-characters'
uvicorn app:app --reload
pytest -q
```

Set `OPENAI_API_KEY` to enable draft generation; this incurs provider charges. Do not commit secrets.

## Render deployment settings
- Runtime: Docker
- Docker context: `./browser-agent`
- Dockerfile: `./browser-agent/Dockerfile`
- Health check path: `/health`
- Required secret: `BOOTSTRAP_TENANT_TOKEN` (32+ random characters)
- Required for production: `APP_ENV=production`, durable `DATABASE_URL`
- Optional secret: `OPENAI_API_KEY`; optional model `OPENAI_MODEL` (defaults to `gpt-4o-mini`)

## Before production use
1. Configure a dedicated durable database; do not reuse CallQ's production database.
2. Execute CI and live API tests against the deployed service.
3. Rotate initial credentials; verify tenant isolation and backup/restore.
4. Add per-tenant rate limits, audit events, idempotency, retention/deletion controls, alerting, and billing/usage limits.
5. Review privacy notice, customer data processing terms, and applicable privacy requirements.
6. Add a vetted web-search/browser provider only after defining allowed domains, SSRF protections, robots/terms handling, and a safe action approval model.

This is an MVP pilot, not yet production-certified.
