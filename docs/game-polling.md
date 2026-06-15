# Game Data Polling

## Responsibility

The polling component continuously checks for today's scheduled game for the configured team, detects state changes and play-by-play events, and enqueues messages for the chat poster.

---

## Scheduling Logic

The poller runs in an infinite loop. The sleep interval between iterations is adaptive:

| Game Status | Poll Interval |
|-------------|---------------|
| No game / far before game | Until 05:00 local (next day reset) |
| Scheduled | ≤ 5 minutes (300 s) |
| Pre-Game, Warmup, Delay, Suspended | ≤ 60 s |
| In Progress | 10 s |
| Final / Game Over / Completed | Resets to default (30 s) |
| Unknown status | 30 s |

"Today" is defined as Central time minus 5 hours, so late-night games (past midnight) are still attributed to the correct game date.

---

## Per-Iteration Flow

```
1. Determine today's game date (Central - 5 h)
2. If date changed since last iteration:
     Load all event IDs for this date from DB into an in-memory set
3. Fetch schedule for team from MLB Stats API
4. If no games:
     If "NoGameToday" event not already posted → enqueue "no game" message, log event
5. For each game in schedule:
   a. Check if game status ID is new → enqueue game-status message, log it
   b. If status == "In Progress":
        Fetch full game data (play-by-play + linescore)
        Fetch formatted linescore string
        For each completed play:
          Build event info dict
          Compute play event ID
          If ID not in seen set → format message, enqueue it, log it
   c. Adjust sleep interval based on status
6. Sleep for computed interval
7. Repeat
```

---

## Event Info Dictionary

When a play is processed, the following fields are assembled for message formatting:

**Team info**
- `homeTeamFullName`, `homeTeamName`, `homeTeamShortFullName`, `homeTeamAbbv`
- `awayTeamFullName`, `awayTeamName`, `awayTeamShortFullName`, `awayTeamAbbv`

**Play metadata**
- `startTime`, `inning`, `inningHalf`, `atBatIndex`
- `balls`, `strikes`, `outs`

**Score**
- `homeScore`, `awayScore`

**Play result**
- `description` — human-readable MLB description
- `event` — MLB event type (e.g. "Home Run", "Strikeout", "Single")
- `rbi` — RBI count from MLB data
- `playType` — MLB type field
- `playTypeActual` — derived type (see Play Type Classification)

**Base state** (post-play)
- `manOnFirst`, `manOnSecond`, `manOnThird` — booleans

**Run accounting**
- `runsScored`, `rbis`, `runsEarned` — summed from runner details

**Linescore snapshot**
- `outs_linescore`, `homeStats_linescore`, `awayStats_linescore`
- `currentInning_linescore`, `inningState_linescore`, `inningHalf_linescore`
- `fullLinescoreString` — pre-formatted multi-line box score

**Strikeout tracker**
- `strikeoutTracker` — `{ home: [bool], away: [bool] }` where `true` = swinging K, `false` = called K

---

## Play Type Classification

Plays are reclassified by scanning the description string. This overrides the MLB `type` field which is unreliable.

| Description contains | Classified as |
|----------------------|---------------|
| "Status Change" | `statusChange` |
| "Mound Visit" | `moundVisit` |
| "Pitching Change" | `pitchingChange` |
| "Defensive Substitution" | `defensiveSubstitution` |
| "Offensive Substitution" | `offensiveSubstitution` |
| "remains in the game" | `remainsInTheGame` |
| "Game Advisory" | `gameAdvisory` |
| "Umpire Substitution" | `umpireSubstitution` |
| "Injury Delay" | `injuryDelay` |
| (none of the above) | `atBat` |

---

## Error Handling

All MLB Stats API calls are wrapped in a retry loop:
- On `HTTPError`: log the status code and response body, then sleep `2*retry + 1` seconds before retrying.
- Maximum 30 retries per call before the loop continues indefinitely (no hard failure).
- Each API call includes a 200 ms sleep before and after to avoid rate-limit fingerprinting.

The TLS stack is patched at startup: if `curl_cffi` is available, all HTTP requests impersonate Chrome to avoid 406 rejections from MLB's CDN on VPS IP ranges.
