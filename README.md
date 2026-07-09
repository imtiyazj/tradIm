# tradIm — Halal Trader

AI-powered Shariah-compliant stock research and paper-trading app.
FastAPI backend + Next.js dashboard, deployed on Railway.

- **Screening**: Zoya (AAOIFI) + financial-ratio fallback via Finnhub/Claude
- **Signals**: Claude morning analysis (news + RSI/MACD + earnings calendar)
- **Trading**: Alpaca (paper by default) with confidence-based position sizing
  and bracket orders; buys are halal-gated at the API level
- **Feedback loop**: nightly forward-return tracking per signal vs SPUS benchmark
  (`/dashboard/performance`)

## Backend environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | yes | Postgres connection string |
| `CLERK_ISSUER` | **yes in prod** | Clerk Frontend API URL (e.g. `https://your-app.clerk.accounts.dev`). **If unset, API auth is DISABLED** — dev only; the server logs a CRITICAL warning |
| `ANTHROPIC_API_KEY` | yes | Claude analysis |
| `ALPACA_KEY` / `ALPACA_SECRET` | yes | Trading + market data |
| `ALPACA_BASE_URL` | no | Defaults to paper (`https://paper-api.alpaca.markets`) |
| `ZOYA_API_KEY` | yes | Shariah screening |
| `FINNHUB_API_KEY` | yes | News + ratio fallback |
| `ALLOWED_ORIGINS` | prod | Comma-separated CORS origins (frontend URL) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | no | Alerts |
| `REDIS_URL` | no | Discovery result cache |

## Frontend environment variables

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend URL |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` / `CLERK_SECRET_KEY` | Clerk auth |

## Scheduled jobs (ET, weekdays unless noted)

| Time | Job |
|---|---|
| 08:00 | Morning analysis — screen, analyse, signal, alert |
| 16:45 | Reconcile trade fills (fixes price=0 rows from unfilled orders) |
| 17:30 | Signal forward-return update (1w/1m/3m vs SPUS) |
| Sun 06:00 | Halal cache refresh |

## Local development

```bash
# backend
cd backend && pip install -r requirements.txt
uvicorn main:app --reload            # needs DATABASE_URL etc. in env

# frontend
cd frontend && npm install && npm run dev
```
