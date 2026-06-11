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

## 9. Marketing videos (optional)

A short-form promo video (YouTube Shorts / TikTok / Instagram Reels) is
generated and published after every successful game publish when
`ENABLE_MARKETING_VIDEOS=true`. ffmpeg is bundled via `imageio-ffmpeg`
(pip) — no system package needed. Enable platforms individually with
`MARKETING_PLATFORMS=youtube,tiktok,instagram`. A platform with missing
credentials is skipped, never fatal.

Voiceover uses OpenAI TTS when `OPENAI_API_KEY` is set, else free gTTS.

### 9a. YouTube — one-time refresh token

1. In [Google Cloud Console](https://console.cloud.google.com) create a
   project, enable **YouTube Data API v3**, and create an **OAuth client ID**
   (type: *Desktop app*). Note the client id and secret.
2. Add your Google account as a test user on the OAuth consent screen
   (publishing the app removes the 7-day token expiry of test mode).
3. Generate the refresh token once on any machine:

```bash
# Visit this URL in a browser (replace CLIENT_ID), grant access, copy the code:
# https://accounts.google.com/o/oauth2/v2/auth?client_id=CLIENT_ID&redirect_uri=urn:ietf:wg:oauth:2.0:oob&response_type=code&scope=https://www.googleapis.com/auth/youtube.upload&access_type=offline&prompt=consent

curl -s https://oauth2.googleapis.com/token \
  -d client_id=CLIENT_ID -d client_secret=CLIENT_SECRET \
  -d code=PASTED_CODE -d grant_type=authorization_code \
  -d redirect_uri=urn:ietf:wg:oauth:2.0:oob
# → copy "refresh_token" into YOUTUBE_REFRESH_TOKEN
```

> Custom thumbnails require a phone-verified channel; the uploader logs a
> warning and continues without one otherwise.

### 9b. TikTok

1. Create an app at [developers.tiktok.com](https://developers.tiktok.com),
   add the **Content Posting API** product, and request the
   `video.publish` scope.
2. Run the OAuth flow for the bot account to obtain an access token and
   open id → `TIKTOK_ACCESS_TOKEN`, `TIKTOK_OPEN_ID`. Tokens expire (24h
   access / 365d refresh) — re-run the flow or wire token refresh when the
   publisher starts failing with 401s.
3. **Until the app passes TikTok's audit, the API forces SELF_ONLY
   (private) visibility.** Set `TIKTOK_PRIVACY_LEVEL=SELF_ONLY` so the
   request matches what TikTok will actually do, then switch to
   `PUBLIC_TO_EVERYONE` after audit approval.

### 9c. Instagram Reels

1. The Instagram account must be a **Business or Creator** account linked
   to a Facebook Page.
2. In [Meta for Developers](https://developers.facebook.com) create an app,
   add the **Instagram Graph API**, and generate a long-lived access token
   with `instagram_basic`, `instagram_content_publish`, and
   `pages_read_engagement` permissions (Graph API Explorer → extend token).
3. `INSTAGRAM_ACCOUNT_ID` is the IG **user id** (not the username): query
   `GET /me/accounts` then `GET /{page-id}?fields=instagram_business_account`.
4. Note: Instagram caps publishing at 25 posts per 24h per account, and
   long-lived tokens expire after ~60 days — refresh them on a calendar
   reminder or the publisher will start logging 401 failures.

## 10. Updating

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
