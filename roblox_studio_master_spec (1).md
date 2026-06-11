# Autonomous Roblox Game Studio — Master Spec Document
### For Claude Code / Fable 5 Autonomous Build

---

## 0. Overview

This system runs on a Hetzner VPS and autonomously finds trending Roblox game opportunities, generates complete games using Luau code + Roblox Toolbox assets, publishes them via Open Cloud API, and monitors performance. No human input is required except for flagged big-decision alerts sent via Discord DM.

**Total estimated monthly cost:** ~$12–18/month (VPS + OpenRouter)  
**Target output:** Variable — meta scout determines publish frequency per cycle  
**Alert channel:** Discord DM (big decisions + weekly digest)

---

## 1. System Architecture

```
Orchestrator (APScheduler, every 6 hours)
│
├── L1: Intelligence Layer (parallel async)
│   ├── MetaScout
│   ├── TrendPredictor
│   ├── MechanicMapper
│   ├── GapAnalyzer
│   └── ScoringEngine → ViabilityGate
│
├── L2: Build Pipeline (sequential)
│   ├── ConceptGenerator
│   ├── LuauAgent (Claude Sonnet)
│   ├── ToolboxAssetResolver
│   ├── RojoBuilder
│   ├── AssetGenerator (thumbnail/icon)
│   └── AutoValidator
│
├── L3: Publish & Market
│   ├── OpenCloudPublisher
│   └── InRobloxMarketer
│
└── L4: LiveOps & Monitor
    ├── PerformanceMonitor
    ├── FeedbackLoop
    └── DiscordReporter
```

---

## 2. Infrastructure

| Component | Service | Cost |
|-----------|---------|------|
| VPS | Hetzner CX21 (~2 vCPU, 4GB RAM) | ~$6/mo |
| Database | PostgreSQL on VPS (self-hosted) | Free |
| LLM API | OpenRouter | ~$2–10/mo variable |
| Image Gen | OpenRouter (FLUX) | ~$0.03–0.06/game |
| Roblox Publish | Open Cloud API | Free |
| Alerts | Discord Webhook | Free |

**Roblox account strategy:** Separate accounts per genre (e.g., `StudioIdle_`, `StudioHorror_`, `StudioSim_`) to reduce TOS flag risk. Each account must be pre-created manually with one blank published place. The `universe_id` and `place_id` for each account are stored in the database.

---

## 3. L1 — Intelligence Layer

### 3.1 MetaScout
**Model:** Gemini Flash (via OpenRouter)  
**Runs:** Every cycle (every 6 hours)  
**Data sources:**
- Roblox Games API — top 50 games by CCU, sorted by sustained CCU (30-day average weighted over spike)
- r/roblox hot posts (Reddit API)
- Roblox DevForum trending threads (web scrape)
- YouTube search "roblox" sorted by upload date (last 72 hours)

**Output schema:**
```json
{
  "signals": [
    {
      "genre": "string",
      "mechanic_tag": "string",
      "signal_strength": 0.0–1.0,
      "source": "string",
      "sustained_ccu_indicator": true/false
    }
  ]
}
```

### 3.2 TrendPredictor
**Model:** Gemini Flash  
**Data sources:**
- TikTok trending sounds/hashtags (scrape or RapidAPI)
- YouTube Shorts view velocity (videos <72 hours old, gaming category)
- Twitter/X gaming discourse (filtered for Roblox-adjacent meme formats)

**Purpose:** Leading indicator — identifies cultural trends outside Roblox that haven't hit the platform yet. Outputs a list of "pre-arrival" trend signals with estimated time-to-Roblox (days).

**Output schema:**
```json
{
  "pre_arrival_trends": [
    {
      "trend_name": "string",
      "platform_origin": "tiktok|youtube|twitter",
      "velocity_score": 0.0–1.0,
      "estimated_days_to_roblox": 0–30,
      "suggested_mechanic": "string"
    }
  ]
}
```

### 3.3 MechanicMapper
**Model:** DeepSeek V3  
**Purpose:** Maps incoming cultural trends to proven Roblox core loop mechanics. Maintains an internal library:

| Mechanic | Description |
|----------|-------------|
| `idle_tycoon` | Build and expand a production facility, prestige loop |
| `pet_collect` | Collect/hatch/trade named entities with rarity tiers |
| `survival_horror` | Escape/survive against a threat, rounds-based |
| `obby` | Obstacle course with checkpoints and cosmetic rewards |
| `rpg_dungeon` | Stats, gear, and dungeon clearing with progression |
| `incremental_sim` | Grow a thing over time, sell for currency, rebirth |

**Output:** Each trend signal gets a `mechanic_tag` appended.

### 3.4 GapAnalyzer
**Model:** DeepSeek V3  
**Purpose:** Scores how differentiated a proposed concept is from the current top-50 live games. If similarity score > 0.8, flags for concept mutation before proceeding.

**Output schema:**
```json
{
  "concept_id": "string",
  "similarity_score": 0.0–1.0,
  "closest_existing_game": "string",
  "differentiation_suggestions": ["string"]
}
```

### 3.5 ScoringEngine + ViabilityGate
**Model:** DeepSeek V3  
**Purpose:** Combines MetaScout + TrendPredictor + GapAnalyzer scores into a final opportunity score. Only concepts scoring above 0.65 pass the viability gate and proceed to the build pipeline.

**Scoring weights:**
- Signal strength (MetaScout): 30%
- Pre-arrival trend velocity: 25%
- Sustained CCU indicator: 25%
- Differentiation score: 20%

**Database write:** Passing concepts are written to `concept_queue` table in Postgres with full JSON payload.

---

## 4. L2 — Build Pipeline

### 4.1 ConceptGenerator
**Model:** DeepSeek V3  
**Input:** Viability-gated concept spec from Postgres  
**Output schema:**
```json
{
  "game_title": "string",
  "tagline": "string",
  "mechanic_tag": "string",
  "core_loop": "string (30-second description)",
  "systems": ["string"],
  "monetization": {
    "game_passes": [{"name": "string", "price_robux": 0, "benefit": "string"}],
    "currency_name": "string",
    "shop_items": [{"name": "string", "price": 0, "type": "cosmetic|boost|unlock"}],
    "vip_server": true/false
  },
  "toolbox_keywords": ["string"],
  "target_genre_account": "string"
}
```

### 4.2 LuauAgent
**Model:** Claude Sonnet (primary) → escalate to Fable if validator fails 3x  
**Purpose:** Generates all Luau scripts for the game using template-based generation.

**Template library (hand-written, tested, stored in `/templates/`):**
- `idle_tycoon_base/` — plot claiming, conveyor production, prestige, upgrade UI
- `pet_collect_base/` — egg hatching, inventory, rarity system, trade UI
- `survival_horror_base/` — round manager, monster AI, lobby, voting
- `incremental_sim_base/` — resource tick, sell loop, rebirth, leaderboard

**Agent instructions:**
1. Load the matching base template
2. Rename systems, items, and currencies to match concept JSON
3. Implement the monetization config (game passes, shop, VIP)
4. Generate `default.project.json` (Rojo format)
5. Output full file tree to `/build/[game_id]/src/`

**Client/server split rules (enforced by agent):**
- All Robux transactions: `ServerScriptService` only
- UI rendering: `StarterPlayerScripts` / `StarterGui`
- RemoteEvents for all client↔server communication
- Never trust the client for currency or stats

### 4.3 ToolboxAssetResolver
**Model:** Gemini Flash  
**Purpose:** Takes `toolbox_keywords` from the concept JSON and resolves them to real Roblox Toolbox asset IDs via the Roblox Catalog/Search API.

**Strategy:**
- Search each keyword, filter for free assets, sort by rating
- Select top-3 results per keyword, store asset IDs
- Asset IDs are injected into the Luau template as `ReplicatedStorage` model references

**Output:** Appends `resolved_assets: [{keyword, asset_id, name}]` to concept JSON.

### 4.4 RojoBuilder
**Purpose:** Headless .rbxl compilation  
**Command:**
```bash
rojo build /build/[game_id]/default.project.json --output /build/[game_id]/game.rbxl
```
**Error handling:** If rojo build fails, capture stderr and feed back to LuauAgent for targeted fix. Max 3 retries before escalating model.

### 4.5 AssetGenerator
**Model:** FLUX via OpenRouter  
**Purpose:** Generates thumbnail (1920x1080) and icon (512x512) for the game.

**Thumbnail prompt template:**
```
Roblox game thumbnail, [game_title], [genre] style, vibrant colors, 
cartoon 3D art style, dynamic action scene, no text overlays, 
high contrast, eye-catching for young audience
```

**Description generator:** DeepSeek V3 writes an SEO-optimized game description using top keywords from MetaScout data. Max 1000 characters. Includes genre keywords, action verbs, and current trending terms.

### 4.6 AutoValidator
**Checks (in order):**
1. Rojo build succeeded (exit code 0)
2. All Luau scripts parse without syntax errors (`luau-analyze`)
3. No script exceeds 200KB
4. TOS keyword scan (blocked terms list — weapons, slurs, adult content)
5. All RemoteEvents have server-side validation present
6. `default.project.json` structure is valid

**On failure:**
- Retry with same model up to 3 times with error context appended
- On 4th failure: escalate to Claude Sonnet → Fable, restart from LuauAgent
- Log all failures to `build_failures` table in Postgres

---

## 5. L3 — Publish & Market

### 5.1 OpenCloudPublisher
**API:** Roblox Open Cloud v2  
**Credentials:** Per-genre Roblox account API keys stored as environment variables  
**Steps:**
1. Upload `.rbxl` to existing place via `POST /universes/{universeId}/places/{placeId}/versions`
2. Set game name and description via `PATCH /universes/{universeId}`
3. Upload thumbnail via `POST /universes/{universeId}/thumbnails`
4. Set place as public
5. Write published game record to `published_games` table

**Rate limiting:** Max 1 publish per genre account per 4 hours.

### 5.2 InRobloxMarketer
**Phase 1 (launch):**
- Set SEO-optimized description generated by AssetGenerator
- Queue 2 thumbnail variants for A/B test (re-run AssetGenerator with alternate prompt)
- Read CTR data after 48 hours, keep winner, discard loser

**Phase 2 (ongoing, weekly):**
- Refresh game description with updated keywords from latest MetaScout run
- Re-score thumbnail CTR monthly, regenerate if CTR < 2%

**Robux ads:** Disabled by default. Pluggable module — enable by setting `ENABLE_ADS=true` and `ADS_BUDGET_ROBUX` env var. Not built in Phase 1.

---

## 6. L4 — LiveOps & Monitor

### 6.1 PerformanceMonitor
**Runs:** Every hour  
**API:** Roblox Analytics API  
**Metrics tracked per game:**
- CCU (concurrent users)
- Session length (average minutes)
- D1 / D7 / D30 retention
- Revenue (Robux earned)
- Thumbnail CTR

**Database schema — `game_metrics` table:**
```sql
game_id UUID, 
universe_id BIGINT, 
timestamp TIMESTAMPTZ, 
ccu INT, 
session_length_avg FLOAT, 
d1_retention FLOAT, 
d7_retention FLOAT, 
revenue_robux INT, 
thumbnail_ctr FLOAT
```

### 6.2 Breakout Detection & Auto-Scaling
**Breakout threshold:** CCU > 200 sustained for 24 hours  
**Automatic actions on breakout:**
1. Increase LuauAgent update frequency for this game (weekly content drops)
2. Regenerate thumbnail with higher-effort FLUX prompt
3. Refresh description daily instead of weekly
4. Send Discord DM alert: "Game [title] hit breakout threshold — [CCU] CCU"

**Underperforming flag (both conditions simultaneously):**
- CCU < 10 for 30 consecutive days AND
- Zero revenue for 14 consecutive days
→ Games are left live (long tail value) but flagged in dashboard. No auto-unpublish.

### 6.3 FeedbackLoop
**Runs:** After each PerformanceMonitor cycle  
**Purpose:** Adjusts ScoringEngine weights based on real performance data  
**Logic:**
- Games that exceed CCU > 50 within 7 days → boost that genre/mechanic signal weight by 10%
- Games that never exceed CCU > 5 after 14 days → reduce that genre/mechanic signal weight by 10%
- Weight adjustments are capped at ±40% from baseline

### 6.4 DiscordReporter
**Weekly digest (every Monday 9am):**
- Total games live
- Top 3 games by CCU
- Revenue last 7 days
- Games that hit breakout / underperform flags
- Next cycle's top-scored opportunity

**Big-decision alerts (immediate):**
- Game crosses 200 CCU (breakout)
- Build failure rate > 50% in last 24 hours
- OpenRouter spend > $15 in 7 days
- Any TOS-flagged content detected pre-publish

---

## 7. Database Schema (Postgres)

```sql
-- Concepts that passed viability gate
CREATE TABLE concept_queue (
  id UUID PRIMARY KEY,
  created_at TIMESTAMPTZ,
  status TEXT, -- 'queued' | 'building' | 'published' | 'failed'
  concept_json JSONB,
  opportunity_score FLOAT,
  genre TEXT,
  mechanic_tag TEXT
);

-- All published games
CREATE TABLE published_games (
  id UUID PRIMARY KEY,
  concept_id UUID REFERENCES concept_queue(id),
  universe_id BIGINT,
  place_id BIGINT,
  genre_account TEXT,
  published_at TIMESTAMPTZ,
  game_title TEXT,
  status TEXT -- 'live' | 'flagged' | 'breakout'
);

-- Hourly metrics per game
CREATE TABLE game_metrics (
  id UUID PRIMARY KEY,
  game_id UUID REFERENCES published_games(id),
  timestamp TIMESTAMPTZ,
  ccu INT,
  session_length_avg FLOAT,
  d1_retention FLOAT,
  d7_retention FLOAT,
  revenue_robux INT,
  thumbnail_ctr FLOAT
);

-- Build failures log
CREATE TABLE build_failures (
  id UUID PRIMARY KEY,
  concept_id UUID,
  timestamp TIMESTAMPTZ,
  stage TEXT,
  error_message TEXT,
  model_used TEXT,
  retry_count INT
);

-- Feedback loop weight adjustments
CREATE TABLE signal_weights (
  mechanic_tag TEXT PRIMARY KEY,
  weight FLOAT DEFAULT 1.0,
  last_updated TIMESTAMPTZ
);
```

---

## 8. AI Model Assignment

| Task | Model | Reason |
|------|-------|--------|
| MetaScout analysis | Gemini Flash | High volume, fast, cheap |
| TrendPredictor | Gemini Flash | High volume, fast |
| MechanicMapper | DeepSeek V3 | Reasoning task, cheap |
| GapAnalyzer | DeepSeek V3 | Reasoning task, cheap |
| ScoringEngine | DeepSeek V3 | Reasoning task, cheap |
| ConceptGenerator | DeepSeek V3 | Creative, cheap |
| LuauAgent (primary) | Claude Sonnet | Code quality critical |
| LuauAgent (escalation) | Claude Fable | Fallback on repeated failure |
| ToolboxAssetResolver | Gemini Flash | Simple lookup, fast |
| AssetGenerator prompts | Gemini Flash | Simple, fast |
| Description/SEO writer | DeepSeek V3 | Writing task, cheap |

All models accessed via OpenRouter using existing API key.

---

## 9. Environment Variables

```bash
# OpenRouter
OPENROUTER_API_KEY=

# Roblox Open Cloud (one per genre account)
ROBLOX_API_KEY_IDLE=
ROBLOX_UNIVERSE_ID_IDLE=
ROBLOX_PLACE_ID_IDLE=

ROBLOX_API_KEY_HORROR=
ROBLOX_UNIVERSE_ID_HORROR=
ROBLOX_PLACE_ID_HORROR=

ROBLOX_API_KEY_SIM=
ROBLOX_UNIVERSE_ID_SIM=
ROBLOX_PLACE_ID_SIM=

# Discord
DISCORD_WEBHOOK_URL=

# Postgres
DATABASE_URL=

# Optional — ads (disabled by default)
ENABLE_ADS=false
ADS_BUDGET_ROBUX=0

# Reddit API
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=

# TikTok / RapidAPI
RAPIDAPI_KEY=
```

---

## 10. Build Order for Claude Code

Build in this exact order — each phase depends on the previous:

**Phase 1 — Data & Intelligence (Hand off first)**
1. Postgres schema setup + migrations
2. MetaScout (Roblox Games API + Reddit scraper)
3. TrendPredictor (TikTok/YouTube scraper)
4. MechanicMapper (static library + mapping logic)
5. GapAnalyzer
6. ScoringEngine + ViabilityGate
7. Orchestrator skeleton (APScheduler, phase coordination)

**Phase 2 — Build Pipeline (Hand off second)**
1. Luau template library — `idle_tycoon_base` first, test in Studio
2. LuauAgent (Sonnet, template customization + Rojo project gen)
3. ToolboxAssetResolver (Roblox Catalog API)
4. RojoBuilder (subprocess wrapper + error capture)
5. AssetGenerator (FLUX thumbnail + description writer)
6. AutoValidator (linter + TOS scan + structure checks)

**Phase 3 — Publish & Ops (Hand off third)**
1. OpenCloudPublisher
2. InRobloxMarketer (A/B thumbnails + description refresh)
3. PerformanceMonitor (Analytics API polling)
4. Breakout detection + auto-scaling logic
5. FeedbackLoop (weight adjustment)
6. DiscordReporter (weekly digest + alerts)

**Phase 4 — Integration**
1. Wire all phases through Orchestrator
2. End-to-end test run (dry-run mode — build but don't publish)
3. First live publish
4. VPS deployment (systemd service)

---

## 11. One-Time Manual Setup (Before First Run)

1. Create Roblox accounts for each genre (idle, horror, sim) — enable 2FA
2. Create one blank published place on each account — save universe_id and place_id
3. Generate Open Cloud API keys for each account with publish permissions
4. Create Hetzner VPS — Ubuntu 22.04, install Python 3.11, Rokit, Rojo, Postgres
5. Set all environment variables
6. Create Discord webhook URL for alerts

**Everything after this is automated.**

---

## 12. Human Oversight Transition

The system launches in **supervised mode** for the first 3–5 games. In this mode:
- The build pipeline runs fully automatically up to and including AutoValidator
- Before OpenCloudPublisher fires, the system pauses and sends a Discord DM with a preview: game title, concept summary, thumbnail, and a one-line approve/skip command
- You respond via Discord (`!approve [game_id]` or `!skip [game_id]`)
- After 5 approved games with no issues, supervised mode disables automatically and the system goes fully autonomous
- Supervised mode can be re-enabled at any time via `SUPERVISED_MODE=true` env var

---

## 13. Roblox Account & Place Strategy

**Recommended:** Multiple games per account (up to 5 places per genre account).

- Each genre account holds up to 5 published places
- When an account hits 5 places, the system creates a new genre account variant (e.g., `StudioIdle2_`) and alerts via Discord to complete the one-time manual setup
- This balances TOS risk (not one mega-account) with operational simplicity (not a new account per game)
- The `published_games` table tracks which place belongs to which account

---

## 14. Live Game Update Cadence

| Game Status | Update Frequency | What Gets Updated |
|-------------|-----------------|-------------------|
| Breakout (CCU > 200) | Daily | New content drop, balance tweak, fresh SEO description |
| Normal (CCU 10–200) | Weekly | Description refresh, minor balance pass |
| Underperforming (CCU < 10) | Monthly | Description keyword refresh only |

Updates are generated by LuauAgent (Sonnet) using the existing game's source as context. Each update is validated and published via the same AutoValidator → OpenCloudPublisher pipeline.

---

## 15. Localization Strategy

The MetaScout tags each trend signal with a `platform_origin_country`. If a trend originates predominantly from a non-English market (ES, PT, DE, FR, PH), the ConceptGenerator flags the game for localization.

**Localized games get:**
- Title and description translated via DeepSeek V3 (cheap, handles common languages well)
- English version always published first; localized version published to the same place as an update within 24 hours
- No in-game text translation in Phase 1 — description/metadata only

---

## 16. TOS Moderation Handling

**Pre-publish:** AutoValidator runs a TOS keyword scan before every publish. If flagged, escalate model and retry (see Section 4.6).

**Post-publish takedown (Roblox moderates the live game):**
- PerformanceMonitor detects place status change to `moderated`
- System immediately pauses all publishing on that genre account
- Discord DM alert sent: "Game [title] on [account] was moderated — place ID [id]. Awaiting your review."
- All other genre accounts continue publishing unaffected
- You investigate and respond; system resumes that account only on manual `!resume [account]` command
- Incident logged to `moderation_incidents` table

---

## 17. Revenue Tracking

- PerformanceMonitor pulls Robux earned per game hourly from Roblox Analytics API
- Stored in `game_metrics.revenue_robux`
- Weekly digest includes total Robux across all games and per-game breakdown
- No automatic DevEx — you cash out manually via Roblox dashboard
- Discord alert if any single game earns > 10,000 Robux in a 7-day window (worth your attention)

---

## 18. VPS Disk Management

- After a successful publish, build files for that game are archived to `/builds/archive/[genre]/`
- Each genre directory keeps the **last 10 builds only** — older ones are deleted automatically post-publish
- `/builds/active/` only ever contains the current in-progress build
- Estimated disk usage: ~50MB per build × 10 per genre × 3 genres = ~1.5GB max. Well within Hetzner CX21 limits.

---

## 19. Account Ban Handling

- PerformanceMonitor checks account status each cycle via Roblox API
- If a genre account is banned or restricted:
  - Publishing pauses for that account only
  - All other genre accounts continue unaffected
  - Discord DM alert: "Account [name] banned/restricted — [genre] publishing paused"
  - Flagged in `genre_accounts` table as `status: paused`
  - You investigate; resume with `!resume-account [genre]` command
- System never auto-creates replacement accounts (requires your manual setup per Section 11)

---

## 20. Viability Gate Fallback

If the viability gate rejects all concepts for **3 or more consecutive cycles** (nothing scores ≥ 0.65):
- On the 4th cycle, lower the viability threshold temporarily to 0.50 for one attempt
- Generate a concept from the highest-scoring signal regardless of score
- If that game publishes successfully, reset threshold to 0.65
- Discord alert: "Viability gate in fallback mode — threshold lowered for this cycle. Top score was [X]."
- This prevents the system from stalling indefinitely during slow meta periods

---

## 21. Acceptance Criteria

The system is complete when:
- [ ] A full cycle runs end-to-end without human input
- [ ] A game is published to a real Roblox account automatically
- [ ] PerformanceMonitor successfully pulls CCU data hourly
- [ ] Discord DM is sent with weekly digest
- [ ] A build failure correctly escalates model and retries
- [ ] FeedbackLoop adjusts signal weights after 7 days of data
- [ ] Orchestrator recovers gracefully from a crashed cycle
- [ ] Supervised mode correctly pauses before publish and resumes on Discord approval
- [ ] After 5 approved games, supervised mode disables and system goes fully autonomous
- [ ] Account ban detection pauses correct genre account, leaves others running
- [ ] Viability fallback triggers correctly after 3 consecutive rejected cycles
- [ ] Disk cleanup correctly keeps last 10 builds per genre only
- [ ] Post-publish TOS takedown triggers Discord alert and account pause
- [ ] Breakout game correctly switches to daily update cadence automatically
- [ ] Localization flag correctly triggers translated description on eligible games
- [ ] Revenue tracked per game hourly, Discord alert fires at 10k Robux/week threshold
