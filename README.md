# pace-core

Personal running coach backend for [PaceCoach](https://github.com/kevinchow08).

Polls COROS watch data after each workout, analyzes it with an LLM, and pushes a coaching summary to your phone.

```
COROS Watch → pace-core → LLM Analysis → Push Notification
```

## Features

- Automatically detects new workouts by polling the COROS API
- Groups multi-segment sessions (warmup + main + cooldown) into one analysis
- Generates post-workout coaching feedback in Chinese via OpenAI-compatible LLM
- Deduplicates: each workout is analyzed and pushed exactly once
- Push notifications via [Ntfy](https://ntfy.sh) (Phase 1), Expo Push (Phase 2)

## Stack

- Python 3.11+
- SQLAlchemy 2.0 + SQLite (deduplication & run logs)
- APScheduler (polling every N minutes)
- OpenAI-compatible SDK (configured for any provider via `base_url`)
- Ntfy for push notifications

## Setup

1. Clone the repo and create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

3. Run once to verify everything works:

```bash
python main.py --once
```

4. Start the scheduler (polls every `POLL_INTERVAL_MINUTES`):

```bash
python main.py
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `COROS_EMAIL` | COROS account email |
| `COROS_PASSWORD` | COROS account password |
| `LLM_API_KEY` | API key for your LLM provider |
| `LLM_BASE_URL` | Base URL for OpenAI-compatible API |
| `LLM_MODEL` | Model name (e.g. `qwen-plus`) |
| `NTFY_TOPIC` | Your Ntfy topic name |
| `DB_URL` | SQLite path (default: `sqlite:///pacecoach.db`) |
| `POLL_INTERVAL_MINUTES` | Polling interval (default: `10`) |

## Roadmap

- [x] Phase 1 v0 — Post-workout analysis push notification
- [ ] Phase 1 v0.1 — Morning sleep briefing
- [ ] Phase 2 — Expo mobile app + conversational coaching agent
