# GWProject Telegram Bot

Telegram webhook bot for authorized defensive checks using the configured API.

## cPanel

Python application settings:

- Python: 3.10+
- Application root: `telegrambot`
- Startup file: `app.py`
- Entry point: `app`

Install dependencies from `requirements.txt`.

## Environment variables

Set these in cPanel; never commit real secrets:

- `BOT_TOKEN` - Telegram BotFather token
- `API_TOKEN` - API token
- `API_URL` - `https://leakosintapi.com/`
- `WEBHOOK_SECRET` - optional random secret for Telegram webhook validation
- `API_LIMIT` - optional, default `100`
- `API_LANG` - optional, default `en`
- `RATE_LIMIT_SECONDS` - optional, default `3`
- `MAX_QUERY_LENGTH` - optional, default `120`

## Endpoints

- `GET /` health check
- `POST /webhook` Telegram webhook endpoint

## Telegram

After the application is running, set the Telegram webhook to:

`https://YOUR-DOMAIN/bot/webhook`

If `WEBHOOK_SECRET` is configured, use the same secret when setting the webhook.
