# Harry 🎙️

A Discord bot named after **Harry Doyle**, the sardonic, bourbon-fueled announcer from *Major League* (voiced by Bob Uecker). Harry delivers real MLB Statcast data with the same dry pessimism he used to narrate the Indians' improbable season.

## Commands

| Command | Description |
|---|---|
| `/strikezone [first] [last] [year]` | Plots a pitcher's strike zone (colored by pitch type) for the given season |
| `/matchup [p_first] [p_last] [b_first] [b_last] [year]` | Head-to-head Statcast stats between a pitcher and batter |

## Quick Start

```bash
# 1. Install dependencies (creates .venv automatically)
cd /path/to/Harry-bot
uv sync

# 2. Set your Discord bot token
cp .env.example .env
# Edit .env and paste your token

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

## Lou's Persona

Errors are delivered in the voice of Lou Brown. Sample:

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
5. Add your `DISCORD_TOKEN` and `OWNER_ID` to the Secrets UI.
6. Deploy the bot via the CLI or UI (if linked to GitHub):
   ```bash
   fly deploy
   ```
