# External API Dependencies

## MLB Stats API

**Library**: `MLB-StatsAPI` (Python wrapper around `https://statsapi.mlb.com`)

The bot makes three distinct API calls during a game:

### 1. Schedule Lookup

Fetches today's game(s) for the configured team.

**Input**: date string (`YYYY-MM-DD`), team ID  
**Returns**: list of game objects

Game object fields used:
| Field | Description |
|-------|-------------|
| `game_id` | Unique numeric game identifier |
| `status` | Game status string (see Status Values) |
| `home_id` | MLB team ID of home team |
| `away_id` | MLB team ID of away team |
| `game_datetime` | ISO 8601 game start datetime |
| `game_num` | Game number (for doubleheaders; 1 or 2) |
| `doubleheader` | `'N'` for single game, otherwise indicates DH |
| `game_date` | `YYYY-MM-DD` string |

### 2. Live Game Data

Fetches complete live game state.

**Input**: `gamePk` (game ID)  
**Returns**: nested game object

Fields used from `liveData`:
- `plays.allPlays` — list of play objects (see Play Object below)
- `linescore` — current linescore state

Linescore fields used:
| Field | Description |
|-------|-------------|
| `outs` | Current out count |
| `currentInning` | Current inning number |
| `inningState` | "Middle" or "End" |
| `inningHalf` | "Top" or "Bottom" |
| `teams.home` | `{runs, hits, errors, leftOnBase}` |
| `teams.away` | `{runs, hits, errors, leftOnBase}` |

Play object fields used:
| Field | Path | Description |
|-------|------|-------------|
| `description` | `result.description` | Human-readable play description |
| `event` | `result.event` | MLB event type string |
| `rbi` | `result.rbi` | RBI count |
| `type` | `result.type` | Play type (not always reliable) |
| `homeScore` | `result.homeScore` | Home score after play |
| `awayScore` | `result.awayScore` | Away score after play |
| `startTime` | `about.startTime` | ISO timestamp |
| `inning` | `about.inning` | Inning number |
| `halfInning` | `about.halfInning` | "top" or "bottom" |
| `atBatIndex` | `about.atBatIndex` | Sequential at-bat counter |
| `balls` | `count.balls` | Ball count |
| `strikes` | `count.strikes` | Strike count |
| `outs` | `count.outs` | Out count |
| `postOnFirst` | `matchup` (key presence) | Runner on first post-play |
| `postOnSecond` | `matchup` (key presence) | Runner on second post-play |
| `postOnThird` | `matchup` (key presence) | Runner on third post-play |
| `runners` | `runners[]` | List of runner movement details |
| `isScoringEvent` | `runners[].details` | Whether runner scored |
| `rbi` | `runners[].details` | Whether runner's score was an RBI |
| `earned` | `runners[].details` | Whether the run was earned |

Plays without a `result.description` are incomplete (at-bat in progress) and are skipped.

### 3. Formatted Linescore

Returns a pre-formatted multi-line ASCII box score string showing runs-hits-errors per inning.

**Input**: game ID  
**Returns**: string

Used verbatim in end-of-inning messages.

### 4. Team Lookup

Fetches team metadata by MLB team ID.

**Input**: team ID  
**Returns**: list with one team object

Team object fields used:
| Field | Description |
|-------|-------------|
| `name` | Full team name |
| `teamName` | Short team name (e.g. "Astros") |
| `shortName` | Short full name |
| `fileCode` | 3-letter abbreviation (lowercase) |

---

## Game Status Values

The following status strings are handled explicitly:

| Status | Phase |
|--------|-------|
| `Scheduled` | Pre-game |
| `Pre-Game` | Pre-game |
| `Warm Up` / `Warmup` | Pre-game |
| `In Progress` | Live |
| `Delayed: Rain` | Live (paused) |
| `Delayed Start: Rain` | Pre-game (paused) |
| `Completed Early: Rain` | Final |
| `Postponed` | Cancelled |
| `Game Over` | Final |
| `Final` | Final |
| `Game Over: Tied` | Final |
| `Final: Tied` | Final |

Any status containing "Delay" or "Suspended" is treated like the delay/suspended group.  
Any unrecognized status is logged as novel and polled at 30 s.

---

## Network Reliability

- All API calls use exponential back-off on `HTTPError` (max 30 retries, delay = `2*attempt + 1` seconds).
- 200 ms sleeps are inserted before and after each API call to avoid rate limiting.
- On environments where the MLB API returns `406` (TLS fingerprinting), `curl_cffi` can be installed to impersonate a Chrome TLS handshake; the library patches the underlying HTTP client transparently.
