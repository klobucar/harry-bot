# Harry 🎙️

A Discord bot named after **Harry Doyle**, the sardonic, bourbon-fueled announcer from *Major League* (voiced by Bob Uecker). Harry delivers real MLB Statcast data with the same dry pessimism he used to narrate the Indians' improbable season.

## Commands

### 📊 Statcast Plots
| Command | Description |
|---|---|
| `/strikezone [first] [last] [year]` | Plots a pitcher's strike zone (colored by pitch type) for the given season |
| `/battedzone [first] [last] [year]` | Plots all pitches thrown to a batter in a season |
| `/spraychart [first] [last] [year]` | Plots where a batter hits the ball on a stadium spray chart |
| `/hotzones [first] [last] [year]` | Show a batter's performance across the strike zone as a 3x3 thermal grid |
| `/matchupzone [p_first] [p_last] [b_first] [b_last] [year]` | Zone plot of one pitcher vs one batter |
| `/stadium [team]` | Show a ballpark's name, location, and visual outline |

### 📈 Stats & Analytics
| Command | Description |
|---|---|
| `/stats [first] [last] [year]` | FanGraphs season stats — auto-detects pitcher or batter |
| `/career [first] [last]` | Career aggregate stats from FanGraphs |
| `/compare [p1] [p2] [year]` | Side-by-side FanGraphs stat comparison of two players |
| `/arsenal [first] [last] [year]` | Pitcher's pitch mix — velocity, spin rate, and usage |
| `/exitvelo [first] [last] [year]` | Batter's exit velocity and barrel stats |
| `/percentile [first] [last] [year]` | Statcast percentile ranks (Higher = better vs. league average) |
| `/hotcold [first] [last] [days]` | Rolling Statcast stats for the last N days (7, 14, or 30) |
| `/leaderboard [stat] [year]` | Top 10 players for any FanGraphs stat (e.g. ERA, WAR, HR) |
| `/junkstats` | Get an absurdly specific and weird baseball fact powered by Gemini |

### ⚔️ Head-to-Head
| Command | Description |
|---|---|
| `/matchup [p_first] [p_last] [b_first] [b_last] [year]` | Head-to-head Statcast text stats: AVG, H, PA, K |

### 🏆 League Info
| Command | Description |
|---|---|
| `/standings [year]` | Show MLB division standings for a given season |
| `/schedule [team] [year]` | Show a team's recent results and upcoming games |
| `/livescore [team]` | Get today's live score for a specific team |
| `/nextgame [team]` | Show a team's next scheduled game and probable pitchers |
| `/roster [team]` | Show a team's current active 26-man roster |
| `/injury [team]` | Show a team's current IL (Injured List) stints |
| `/transactions [team]` | Show recent roster moves for a team |

## Quick Start

```bash
# 1. Install dependencies (creates .venv automatically)
cd /path/to/Harry-bot
uv sync

# 2. Set your API tokens
cp .env.example .env
# Edit .env and paste your DISCORD_TOKEN and GEMINI_API_KEY

# 3. Run the bot
export DISCORD_TOKEN=your_token_here
export OWNER_ID=your_discord_id_here  # Optional: locks DMs to you
uv run python main.py

# Or use the installed script entrypoint:
uv run harry
```

## Running Tests

```bash
uv run pytest
```

## Architecture

- **[discord.py](https://discordpy.readthedocs.io/)** — async Discord gateway + slash commands via `app_commands`
- **[pybaseball](https://github.com/jldbc/pybaseball)** — Statcast / Baseball Savant data + `plotting.plot_strike_zone()`
- **`asyncio.to_thread()`** — all blocking pybaseball/matplotlib calls run in a thread pool so the event loop stays responsive
- **`interaction.response.defer(thinking=True)`** — prevents Discord's 3-second interaction timeout
- **`plt.close(fig)`** — called after every plot save to prevent matplotlib memory leaks
- **[Gemini 2.5 Flash Lite](https://ai.google.dev/)** — powers `/junkstats` via the `google-genai` SDK for absurdly specific baseball facts

## Memory Optimization

Harry is optimized to run in resource-constrained environments (e.g., a **256MB** Fly.io container).

- **PyArrow Zero-Copy Engine**: Monkey-patched Pandas to use the PyArrow C++ engine for all CSV/JSON reads. This reduced peak memory usage during data fetching from ~250MB to **<5MB**.
- **Global Sentinel Lazy Loading**: Matplotlib and Pybaseball modules are deferred using a sentinel pattern in `statcast.py`. They are only initialized on the first command execution, keeping the idle RAM floor as low as possible.
- **Headless Plotting**: The `Agg` backend is forced globally in `main.py` to prevent loading heavy GUI frameworks (Tkinter/Qt).
- **Lean Discord Client**: Internal message and member caching is disabled in `HarryBot` to prevent memory bloat over time.

## Harry's Persona

Errors are delivered in the voice of Harry Doyle. Sample:

> *"Juuust a bit outside... of what I can find. No results, pal."*

## Bot Permissions

In the Discord Developer Portal, enable:
- `bot` scope
- `applications.commands` scope
- Send Messages + Attach Files + Embed Links permissions

## Deploying to Fly.io

Harry is configured to deploy as a background worker on Fly.io using the included `Dockerfile` and `fly.toml`.

1. Install the `flyctl` CLI to set up the app.
2. Initialize the app without deploying:
   ```bash
   fly launch --no-deploy
   ```
3. Open the [Fly.io Dashboard](https://fly.io/dashboard) in your browser.
4. Navigate to your new `harry-bot` app -> **Secrets**.
5. Add your `DISCORD_TOKEN`, `GEMINI_API_KEY`, and `OWNER_ID` to the Secrets UI.
6. Deploy the bot via the CLI or UI (if linked to GitHub):
   ```bash
   fly deploy
   ```
