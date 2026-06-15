# Configuration Reference

## Runtime Settings (`settings.json`)

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `DB_FILE` | string | Yes | Path to the SQLite database file |
| `TEAM_ID` | integer | Yes | MLB numeric team ID of the team to follow |

## Platform Settings (sensitive, not committed)

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `DISCORD_CLIENT_ID` | string | Yes | Application client ID |
| `DISCORD_CLIENT_SECRET` | string | Yes | Application client secret |
| `DISCORD_TOKEN` | string | Yes | Bot token |
| `DISCORD_GAME_THREAD_CHANNEL_ID` | string | Yes | Channel for game threads |
| `DISCORD_GUILD` | string | Yes | Server/guild ID |
| `ANNOUNCEMENT_CHANNEL` | string | Yes | Announcement channel ID |
| `DELETE_ANNOUNCEMENT` | boolean | No (default: false) | Whether to delete announcement after game |

## Tunable Constants (in source)

| Constant | Default | Description |
|----------|---------|-------------|
| `DELAY` | 30 s | Spoiler delay before posting live events |
| `DEFAULT_DELAY` | 30 s | Value DELAY resets to after a game ends |
| Max vote delay | 120 s | Upper bound on user-requested delay |
| Vote duration | 30 s | How long the !delay vote stays open |
| Thread close delay | 1800 s (30 min) | How long after game end before thread is archived |
| DB pruning window | 7 days | How long posted_events rows are kept |

## MLB Team IDs (reference)

The bot uses the MLB Stats API numeric team ID. Common examples:

| Team | ID |
|------|----|
| Houston Astros | 117 |
| New York Yankees | 147 |
| Los Angeles Dodgers | 119 |
| Boston Red Sox | 111 |
| Chicago Cubs | 112 |

All 30 teams are enumerated in `teams.json`.
