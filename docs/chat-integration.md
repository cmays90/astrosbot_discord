# Chat Platform Integration

This document describes the chat platform integration layer. The current implementation targets Discord; this spec describes behavior that should be replicated in any re-implementation.

---

## Required Platform Capabilities

| Capability | Used For |
|------------|----------|
| Send message to channel | Parent message for thread creation |
| Create thread on message | Per-game discussion thread |
| Send message to thread | All game updates |
| Send embed in thread | Game status notifications |
| Create scheduled event | Advance notice of game; linked to thread |
| Start scheduled event | When game begins |
| Complete scheduled event | When game ends |
| Post to announcement channel | Distribute event invite link |
| Publish/cross-post announcement | Push to followers |
| Delete announcement message | Optional cleanup after game ends |
| Archive + lock thread | 30 minutes after game ends |
| React to message with emoji | Delay-vote poll UI |
| Listen for reaction events | Tally delay-vote |
| Bot command handling | `!delay` command |

---

## Thread Lifecycle

```
Game "Scheduled" status detected
  → Create parent message in game-thread channel
  → Create thread on that message
  → Create platform scheduled event (start time = game start, end = +24h, location = thread URL)
  → Post announcement in announcement channel with event invite link
  → Cross-post announcement
  → Store: game_id → thread_id, game_id → event_id, game_id → announcement_msg_id

Game "In Progress" status detected (first time)
  → Start the platform scheduled event
  → Apply spoiler delay before posting further events (if delay > 0)

Game ends (Final / Game Over / Completed / Tied variants)
  → Complete the platform scheduled event
  → Optionally delete the announcement message (configurable)
  → Schedule thread archive+lock after 30 minutes

```

---

## Message Queue Item Schema

The poller enqueues items as dicts. The poster reads and acts on these fields:

| Field | Type | Description |
|-------|------|-------------|
| `game_id` | str \| None | MLB game ID; `None` for "no game today" messages |
| `msg` | str | Plain text to post to thread |
| `embed` | Embed object | Rich embed to post to thread |
| `active_game` | bool | If true, apply the spoiler delay before posting |
| `extras.event_start` | bool | Trigger "start" on the platform scheduled event |
| `extras.event_end` | bool | Trigger "end" lifecycle (complete event, delete announcement, schedule thread close) |

Either `msg` or `embed` may be empty/absent. Both can be present and will both be posted.

---

## Spoiler Delay

A configurable integer (seconds, default 30, max 120) is applied before posting when `active_game == True`. This allows users watching a broadcast on delay to vote to offset live alerts.

The delay is a global mutable value. It resets to the default at the end of each game.

---

## `!delay` Command

Available only inside a game thread (or a hardcoded fallback channel).

Behavior:
1. If called with no argument: reply with current delay value.
2. If called with an integer argument:
   - Clamp value to [0, 120].
   - If a vote is already running: reply with error.
   - Otherwise: post a 30-second vote with two reaction options (Yes / No).
   - Poll reactions every 5 seconds for 30 seconds.
   - If Yes wins: set the global delay to the requested value, confirm in chat.
   - If No wins: confirm delay unchanged.

---

## Configuration

| Setting | Description |
|---------|-------------|
| `DISCORD_TOKEN` | Bot authentication token |
| `DISCORD_CLIENT_ID` | Bot application client ID |
| `DISCORD_CLIENT_SECRET` | Bot application client secret |
| `DISCORD_GUILD` | Guild (server) ID |
| `DISCORD_GAME_THREAD_CHANNEL_ID` | Channel where game thread parent messages are posted |
| `ANNOUNCEMENT_CHANNEL` | Channel for cross-posted game announcements |
| `DELETE_ANNOUNCEMENT` | Boolean: delete announcement after game ends |

---

## Team Flair / Emoji

Each team has a platform-specific emoji string (`flair`) used in the thread creation summary, and a short 3-letter abbreviation (`short`) used in thread names. These are stored in a static lookup file keyed by numeric MLB team ID.
