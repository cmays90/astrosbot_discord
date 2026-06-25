# Astros Bot — Feature Roadmap

## Context

The bot ([docs/overview.md](docs/overview.md)) monitors live Astros games (MLB team 117) and streams play-by-play into auto-managed Discord game threads. This roadmap covers seven new features (an eighth — scoring-play GIFs — is deferred). The work splits cleanly into two layers that already exist:

- **Data + formatting helpers** — pure module-level functions in [BaseballConsumer/BaseballConsumerV2.py](BaseballConsumer/BaseballConsumerV2.py), mirroring the existing `build_lineups_message()` (line 53) and `current_pitcher_count()` (line 87). Easy to unit-test.
- **Wiring** — enqueue points in the poll loop `run()` (line 107) and posting/commands in [BaseballConsumer/MainEntryBot.py](BaseballConsumer/MainEntryBot.py) (`discord_poster` line 212, `BaseballCog` line 340).

All new posts ride the existing queue (`{'msg', 'embed', 'active_game', 'game_id', 'reactions', 'extras'}`) and dedup via the in-memory `ids_of_prev_events` set + `_log_event()` (line 406), with deterministic event IDs like `Lineups;<game_id>`.

### Decisions
- **WPA alert**: fire when a single play swings win probability **≥20 points in the Astros' favor**.
- **Due-up**: `/due-up` shows the **team batting now**, AND **auto-post at end of each half-inning** for the team coming to bat.
- **Auto-react**: react to **all Astros scoring plays** (any play where the Astros are batting and a run scores) with 🚀.
- **Scoring-play GIFs**: **deferred** for now.

---

## Feature 1 — Due-up (`/due-up` command + end-of-inning auto-post)

**New helper** in `BaseballConsumerV2.py` (near `build_lineups_message`, line 53):
```
build_due_up_message(game_data, side=None) -> str | None
```
- `side=None` → use `game_data['liveData']['linescore']['offense']` keys `batter`/`onDeck`/`inHole` (each `{id, fullName}`) — exactly the next 3 for whoever is at bat. Used by the `/due-up` command.
- `side in {'home','away'}` → compute from that team's `boxscore.teams[side].battingOrder` (9 IDs) and the count of that side's completed plate appearances (`len([p for p in allPlays if p batted for side and 'description' in p['result']]) % 9`); take that index + next 2 (mod 9). Used by the end-of-inning post, where `linescore.offense` may not have flipped yet.
- Returns a ```` ``` ````-fenced block like `build_lineups_message` (reuse its row-formatting style: `#. Name Pos`).

**Command** `/due-up` in `BaseballCog` (`MainEntryBot.py`) — mirror `/lineups` (line 407): `@app_commands.command(name='due-up', ...)` (Discord allows hyphens in command names), thread-check via `_db_get_game_by_thread`, `interaction.response.defer` → `build_due_up_message(game)` → `followup.send`.

**End-of-inning auto-post** — in the play loop (`run`, ~line 303 where `pitcherCount` is set), the fielding side is already computed as `pitching_side` (line 302). Add `info['dueUp'] = build_due_up_message(game_info, side=pitching_side)`. Then in `end_of_inning(info)` (line 618), when `outs == "3"`, append `info['dueUp']` (the team coming to bat = the fielding side of the half just ended). No new queue item needed — it rides the existing end-of-inning message.

---

## Feature 2 — WPA swing alert (Astros, ≥20-pt swing)

The `statsapi.get('game', ...)` feed already fetched as `game_info` (line 219) includes `liveData['winProbability']` — one entry per play with `atBatIndex` and `homeTeamWinProbabilityAdded` (signed, home perspective, in points).

**New helper** in `BaseballConsumerV2.py`:
```
astros_wpa_added(game_info, at_bat_index, team_id, home_id) -> float | None
```
- Build `{atBatIndex: homeTeamWinProbabilityAdded}` from `winProbability`.
- Astros swing = `wpAdded` if `home_id == team_id` else `-wpAdded`.

**Formatter** `format_wpa_alert(info, swing) -> str` — short hype line + the play description (reuse `info` fields).

**Wiring** — in the per-play dedup block (`run`, ~line 332), after enqueuing the normal message: compute `swing = astros_wpa_added(game_info, int(info['atBatIndex']), self.TEAM_ID, game['home_id'])`; if `swing is not None and swing >= constants.WPA_ALERT_THRESHOLD`, enqueue a separate item with dedup id `WPA;<game_id>;<atBatIndex>` (check `ids_of_prev_events`, `_log_event`, add to set).

Constant: `WPA_ALERT_THRESHOLD = 20` in `BaseballConsumerConstants.py`.

---

## Feature 3 — Final game summary

**New helper** in `BaseballConsumerV2.py`:
```
build_final_summary(game_data, team_id) -> discord.Embed
```
Pulls from a fresh `statsapi.get('game', ...)`:
- Final R/H/E line — `liveData.linescore.teams`.
- W/L/SV pitchers — `liveData.decisions` (`winner`/`loser`/`save`, each `{id, fullName}`).
- Home runs — iterate `liveData.plays.allPlays` for `result.event == 'Home Run'` (batter from `matchup.batter.fullName`).
- Top performer — best batting line from `boxscore.teams[*].players[*].stats.batting` (hits/HR/RBI).

**Wiring** — in `run()`, where the game-status change is detected (~line 169), when `game_status` is terminal (`'Game Over'`, `'Final'`, tie variants) and `FinalSummary;<game_id>` not in `ids_of_prev_events`: build the embed, enqueue `{'embed': summary, 'game_id': game['game_id']}`, `_log_event`, add to set. Dedup id ensures Game Over→Final don't double-post. Posts independently of the existing win-message logic in `postGameStatusOnDiscord` (line 513).

---

## Feature 4 — `/standings` command (AL West)

**New helper** in `BaseballConsumerV2.py`:
```
build_standings_message(division_id, league_id) -> str
```
Use `statsapi.standings_data(leagueId=league_id, ...)` (filter the returned dict to `division_id`); format a compact monospace table (Rank, Team, W-L, GB) in a ```` ``` ```` block.

**Command** `/standings` in `BaseballCog` — like `/lineups` but **no thread check** (usable anywhere): defer → `build_standings_message(constants.DIVISION_ID, constants.LEAGUE_ID)` → followup.

Constants: `DIVISION_ID = 200` (AL West), `LEAGUE_ID = 103` (AL).

---

## Feature 7 — Auto-react to Astros scoring plays

**`discord_poster` change** (`MainEntryBot.py`, ~line 282) — capture the sent message and apply reactions:
```python
sent = None
if 'msg' in item and item['msg']:
    sent = await thread.send(item['msg'])
elif 'embed' in item and ...:
    sent = await thread.send(embed=item['embed'])
for emoji in item.get('reactions', []):
    if sent: await sent.add_reaction(emoji)
```
(Keep the existing embed-then-msg send order; attach reactions to whichever message object was created.)

**Wiring** — in the per-play enqueue (`run`, line 337): determine if the Astros are batting this play (`homeTeamBatting(info)` vs which side is `self.TEAM_ID` from `game['home_id']/'away_id']`) and a run scored (`info['runsScored'] > 0`). If so, add `'reactions': [constants.EMOTE_ASTROS_SCORE]` to the queued item.

Constant: `EMOTE_ASTROS_SCORE = "🚀"` in `BaseballConsumerConstants.py`.

---

## Files touched

| File | Change |
|------|--------|
| `BaseballConsumer/BaseballConsumerV2.py` | New helpers: `build_due_up_message`, `astros_wpa_added` + `format_wpa_alert`, `build_final_summary`, `build_standings_message`, `build_pregame_message`. Wiring in `run()` (due-up into `info`, WPA enqueue, final-summary enqueue, pregame enqueue, scoring reactions); append due-up in `end_of_inning`. |
| `BaseballConsumer/MainEntryBot.py` | New slash commands `/due-up`, `/standings` in `BaseballCog`; `discord_poster` captures sent message + applies `reactions`; add new helpers to the import block (line 20). |
| `BaseballConsumer/BaseballConsumerConstants.py` | `WPA_ALERT_THRESHOLD=20`, `DIVISION_ID=200`, `LEAGUE_ID=103`, `EMOTE_ASTROS_SCORE="🚀"`, plus pregame/summary embed title strings. |

Slash commands auto-sync to the guild on startup via `AstrosBot.setup_hook()` (line 460) / `!sync` (line 425) — no extra sync work.

---

## Verification

1. **Unit tests** (mirror [tests/test_win_message.py](tests/test_win_message.py)): one test per pure helper (`build_due_up_message`, `astros_wpa_added`, `build_final_summary`, `build_standings_message`, `build_pregame_message`) using hand-built fixture dicts. The `winProbability` / `decisions` / `probablePitchers` blocks may need adding to fixtures — capture a real game with [tests/fixtures/record_game.py](tests/fixtures/record_game.py) or extend `build_minimal_fixture` in `tests/mocks/mlb_mock.py`.
2. **Scenario tests** ([tests/scenarios/](tests/scenarios/test_full_game.py)): drive a full game through `Harness`; assert a due-up block, a WPA alert, and a final-summary embed appear in `MockBot` output, and that a scoring play carries a 🚀 reaction.
3. **Run the suite**: `pytest` from repo root (config in `pytest.ini`, `asyncio_mode=auto`).
4. **Live smoke** (optional): `Harness(mlb, RealDiscordBackend('discordSettings.test.doNotUpload.json'))` against a recorded game to eyeball formatting of embeds/commands in a real test server.

## Suggested build order
1. Constants + `discord_poster` reactions plumbing (unblocks #7).
2. Pure helpers (#1, #4 first — simplest; then #2, #3, #6/#8).
3. `run()` wiring for each, one at a time, with a scenario-test check after each.
4. Slash commands `/due-up`, `/standings`.
