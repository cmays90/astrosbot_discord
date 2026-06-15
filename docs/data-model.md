# Data Model

All persistent state is stored in a single SQLite database (path configured at runtime).

---

## Tables

### `posted_events`

Deduplication log. One row per unique game event that has been posted to chat.

| Column      | Type | Description |
|-------------|------|-------------|
| event_id    | TEXT PK | Deterministic ID built from event attributes (see Event ID section) |
| game_date   | TEXT | `YYYY-MM-DD` of the game (Central time, shifted back 5 hours so late-night games stay on the right date) |
| description | TEXT | Human-readable description of the event |
| logged_at   | TEXT | `YYYY/MM/DD HH:MM:SS` wall-clock time when the row was inserted |

Index: `game_date` (for fast daily load).  
Retention: rows older than 7 days are pruned on startup.

### `game_threads`

Maps a game to the chat thread created for it.

| Column    | Type | Description |
|-----------|------|-------------|
| game_id   | TEXT PK | MLB game ID |
| thread_id | TEXT | Platform thread/channel ID |

### `game_events`

Maps a game to the platform scheduled-event created for it.

| Column   | Type | Description |
|----------|------|-------------|
| game_id  | TEXT PK | MLB game ID |
| event_id | TEXT | Platform scheduled-event ID |

### `game_announcements`

Maps a game to the announcement message posted in the announcement channel.

| Column  | Type | Description |
|---------|------|-------------|
| game_id | TEXT PK | MLB game ID |
| msg_id  | TEXT | Platform message ID of the announcement |

---

## Event ID Construction

Event IDs are concatenated strings that uniquely identify a moment in a game. Different event types use different keys:

| Event Type | ID Format |
|------------|-----------|
| No game today | `NoGameToday` + `YYYY-MM-DD` |
| Game status change | `<status_no_spaces>` + `;` + `<game_id>` |
| At-bat / play | `<startTime>` + `;` + `<outs>` + `;` + `<inning>` + `;` + `<homeScore>` + `;` + `<awayScore>` + `;` + `<atBatIndex>` |

---

## External Data (read-only files)

### `teams.json`

Lookup table for all 30 MLB teams keyed by numeric MLB team ID.

```json
{
  "<team_id>": {
    "flair": "<platform_emoji_string>",
    "short": "<3-letter_abbreviation>"
  }
}
```

### `settings.json`

Runtime configuration (non-sensitive).

```json
{
  "DB_FILE": "<path_to_sqlite_db>",
  "TEAM_ID": <mlb_numeric_team_id>
}
```

### `discordSettings.json` (sensitive — not committed)

Platform credentials and channel configuration.

```json
{
  "DISCORD_CLIENT_ID": "...",
  "DISCORD_CLIENT_SECRET": "...",
  "DISCORD_TOKEN": "...",
  "DISCORD_GAME_THREAD_CHANNEL_ID": "...",
  "DISCORD_GUILD": "...",
  "ANNOUNCEMENT_CHANNEL": "...",
  "DELETE_ANNOUNCEMENT": false
}
```
