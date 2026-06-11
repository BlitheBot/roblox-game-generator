# Deployment — Ubuntu 22.04 VPS

Step-by-step setup for the Autonomous Roblox Game Studio on a fresh
Ubuntu 22.04 VPS (Hetzner CX21 or similar, per spec Section 11).
Estimated time: ~30 minutes plus the one-time Roblox account setup.

## 1. System packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl unzip postgresql postgresql-contrib \
    software-properties-common
```

Ubuntu 22.04 ships Python 3.10 — install 3.11 from deadsnakes:

```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

## 2. Service user and directories

```bash
sudo useradd -m -s /bin/bash studio
sudo mkdir -p /builds/active /builds/archive
sudo chown -R studio:studio /builds
```

## 3. Rojo (and optional luau-analyze)

Install the Rojo binary directly so no Rokit project manifest is needed:

```bash
curl -fsSL -o /tmp/rojo.zip \
  https://github.com/rojo-rbx/rojo/releases/download/v7.6.1/rojo-7.6.1-linux-x86_64.zip
sudo unzip -o /tmp/rojo.zip -d /usr/local/bin && sudo chmod +x /usr/local/bin/rojo
rojo --version
```

> If you use Rokit instead, the `rojo` on PATH is a shim that requires a
> project manifest — point `ROJO_BINARY` in `.env` at the real binary
> under `~/.rokit/tool-storage/`.

Optional (stricter validation; AutoValidator degrades gracefully without it):
install `luau-analyze` from https://github.com/luau-lang/luau/releases and
place it on PATH.

## 4. PostgreSQL

```bash
sudo -u postgres psql -c "CREATE USER studio WITH PASSWORD 'CHANGE_ME';"
sudo -u postgres createdb -O studio roblox_studio
```

Migrations run automatically at every service start — no manual schema step.

## 5. Application

```bash
sudo -iu studio
git clone https://github.com/BlitheBot/roblox-game-generator.git
cd roblox-game-generator
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env
```

Fill in `.env` (see spec Sections 9 and 11):

- `DATABASE_URL=postgresql://studio:CHANGE_ME@127.0.0.1:5432/roblox_studio`
- `OPENROUTER_API_KEY` — from openrouter.ai
- `ROBLOX_API_KEY_IDLE/HORROR/SIM` + `ROBLOX_UNIVERSE_ID_*` — one set per
  genre account (create accounts, generate Open Cloud keys with publish
  permissions; spec Section 11)
- `ROBLOX_PLACE_IDS_*` — comma-separated pool of pre-created place ids per
  account (each game occupies its own place, spec 13; start with 1–5 blank
  published places and add more when the Discord capacity alert fires)
- `DISCORD_WEBHOOK_URL` — alerts + weekly digest channel
- `DISCORD_BOT_TOKEN` + `DISCORD_OWNER_ID` — DM approval flow (create a bot
  at discord.com/developers, enable the *Message Content* intent, DM it once
  so it can DM you back)
- `REDDIT_CLIENT_ID/SECRET`, `RAPIDAPI_KEY` — intelligence sources
- `BUILDS_ROOT=/builds`
- Leave `SUPERVISED_MODE=` empty — it starts supervised and auto-disables
  after 5 approved publishes (spec Section 12)

## 6. Verify with a dry run (required before going live)

Keyless smoke test against the bundled mock LLM server:

```bash
.venv/bin/python scripts/mock_openrouter.py &
DRY_RUN=true OPENROUTER_API_KEY=mock \
OPENROUTER_BASE_URL=http://127.0.0.1:8901/api/v1 \
.venv/bin/python -m scripts.dry_run
kill %1
```

Then the real dry run with your actual keys (builds real concepts with real
LLMs, compiles .rbxl, but never touches Roblox):

```bash
.venv/bin/python -m scripts.dry_run
```

Both must print `RESULT: PASS` (exit 0). Inspect a generated
`/builds/active/<id>/game.rbxl` in Roblox Studio if you want a final
eyeball check.

## 7. Install and start the service

```bash
exit  # back to your sudo user
sudo cp /home/studio/roblox-game-generator/deploy/roblox-studio.service \
    /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now roblox-studio
```

Watch it:

```bash
sudo systemctl status roblox-studio
sudo journalctl -u roblox-studio -f
```

The first intelligence cycle runs immediately on startup; the first build
will land in the Discord DM approval queue (supervised mode). Respond
`!approve <game_id>` or `!skip <game_id>`.

## 8. Updating

```bash
sudo -iu studio bash -c 'cd roblox-game-generator && git pull && .venv/bin/pip install -r requirements.txt'
sudo systemctl restart roblox-studio
```

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Service flapping | `journalctl -u roblox-studio -e` — usually a missing env var or Postgres auth |
| `rojo build failed … project manifest` | PATH rojo is a Rokit shim — set `ROJO_BINARY` |
| No Discord DMs | Bot token/owner id unset, or Message Content intent disabled; previews fall back to the webhook channel |
| Publishes deferred | 4h per-account cooldown (spec 5.1) or genre account paused — `!resume <genre>` after review |
| Publish fails with `no free place` | Place pool exhausted — create a new place on that account and append its id to `ROBLOX_PLACE_IDS_*` |
| Model errors on every LLM call | OpenRouter may have delisted a model — override via `LLM_MODEL_*` / `IMAGE_MODEL` in `.env` |
