# astrosbot_discord

A Discord bot that follows a single MLB team through the season and posts live, play-by-play game threads — pre-game lineups, at-bat events, scoring plays, pitching changes, and a final result — with almost no manual intervention.

Originally based on [KimbaWLion/DiscordBaseballBot](https://github.com/KimbaWLion/DiscordBaseballBot); this version has diverged substantially (async event queue, SQLite-backed exactly-once delivery, spoiler delay voting, due-up/lineup/pitch-count cards, and more).

## How it works

Three concurrent pieces, tied together by an async queue and a SQLite log of already-posted events:

```
Game Data Poller  →  Message Queue  →  Chat Poster  →  Discord
 (MLB Stats API)      (async FIFO)                       │
                                                    Persistence (SQLite)
```

- **Poller** — polls the [MLB Stats API](https://statsapi.mlb.com) on an adaptive schedule (slower when nothing's happening, every 10s once a game is live) and enqueues new events.
- **Queue** — decouples polling from posting so a slow Discord call never stalls the poller.
- **Poster** — creates a per-game thread before first pitch, streams updates into it, and archives it 30 minutes after the game ends.

Every event is assigned a deterministic ID and logged, so restarts and retries never double-post.

Full behavioral spec (useful if you want to re-implement this in another language, or just want the details): see [docs/index.md](docs/index.md).

## Features

- Auto-created game thread per day, with a scheduled Discord event and cross-posted announcement
- Live at-bat updates, scoring plays, "now up" / due-up batter tracking, pitching changes
- Configurable win message (static or rotating list of links/GIFs)
- `/lineups` — starting lineups for both teams
- `/due-up` — next three batters due up
- `!pitchcount` (alias `!pc`) — both active pitchers' pitch counts
- `!delay <seconds>` — vote to add a spoiler delay (0–120s) before events post, for people watching on a broadcast delay
- Self-recovers from transient MLB API failures with exponential backoff

## Setup

Requires Python 3 (developed against 3.14).

```bash
git clone https://github.com/cmays90/astrosbot_discord.git
cd astrosbot_discord
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Two config files, both at the repo root:

**`settings.json`** (safe to commit, no secrets) — see [docs/configuration.md](docs/configuration.md) for the full reference:

```json
{
  "DB_FILE": "BaseballConsumer/logs/game_events.db",
  "TEAM_ID": 117,
  "WIN_MESSAGES": ["https://example.com/celebration.gif"]
}
```

`TEAM_ID` is the MLB numeric team ID of the team to follow (117 = Houston Astros). All 30 team IDs are listed in [teams.json](teams.json).

**`discordSettings.doNotUpload.json`** (secrets — gitignored, create this yourself, never commit it):

```json
{
  "DISCORD_CLIENT_ID": "your-application-client-id",
  "DISCORD_CLIENT_SECRET": "your-application-client-secret",
  "DISCORD_TOKEN": "your-bot-token",
  "DISCORD_GAME_THREAD_CHANNEL_ID": "channel-id-for-game-threads",
  "DISCORD_GUILD": "your-guild-id",
  "ANNOUNCEMENT_CHANNEL": "channel-id-for-announcements",
  "DELETE_ANNOUNCEMENT": false,
  "OWNER_ACCOUNT_ID": 0
}
```

Your Discord application needs the `bot` and `applications.commands` scopes, and the bot needs permission to manage threads, send messages, manage events, and add reactions/polls in the configured guild.

### Running

```bash
python BaseballConsumer/MainEntryBot.py
```

The bot logs to stdout and to `BaseballConsumer/logs/bot.log` (rotated, ~1 GB max retained).

On first run in a new guild, have the bot owner (matching `OWNER_ACCOUNT_ID`) run `!sync` in any channel to register the slash commands.

## Testing

```bash
pip install -r requirements.txt
pytest
```

Tests run fully offline against mocked Discord and MLB Stats API clients (`tests/mocks/`), replaying captured real game data from `fixtures/`. See [scripts/capture_game.py](scripts/capture_game.py) to record a new fixture and [scripts/replay_to_discord.py](scripts/replay_to_discord.py) to replay one against a real Discord server for manual testing.

## Project layout

```
BaseballConsumer/       Bot source (entry point, poller/poster, cards/embeds)
docs/                   Implementation-agnostic spec of the whole system
scripts/                Fixture capture/replay, misc dev tooling
tests/                  Pytest suite, mocks, scenario fixtures
settings.json           Non-secret runtime config
teams.json              MLB team ID → name/abbreviation/flair lookup
```

## License

MIT — see [LICENSE](LICENSE).
