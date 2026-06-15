# Message Formatting

All messages are plain text (with optional rich embeds). Formatting targets a monospace code block for the game situation display, followed by plain text for the play description and emoji reactions.

---

## Game Status Messages

Each game status transition produces an embed + optional body text. All strings are configurable constants.

| Status | Title Constant | Description Constant | Notes |
|--------|---------------|----------------------|-------|
| No Game Today | `NO_GAME_STATUS_TITLE` | `NO_GAME_STATUS_DESCRIPTION` | Only posted once per day |
| Scheduled | `SCHEDULED_GAME_STATUS_TITLE` | `SCHEDULED_GAME_STATUS_DESCRIPTION` | Triggers thread creation |
| Pre-Game | `PREGAME_TITLE` | `PREGAME_DESCRIPTION` | |
| Warm Up | `WARMUP_TITLE` | `WARMUP_DESCRIPTION` | Also attaches an image URL |
| In Progress (first time) | `GAMESTARTED_TITLE` | `GAMESTARTED_DESCRIPTION` | Marks `event_start` |
| Delayed: Rain | `RAINDELAY_TITLE` | `RAINDELAY_DESCRIPTION` | |
| Completed Early: Rain | `COMPLETEDEARLYRAIN_TITLE` | `COMPLETEDEARLYRAIN_DESCRIPTION` | Marks `event_end` |
| Postponed | `POSTPONED_TITLE` | `POSTPONED_DESCRIPTION` | |
| Game Over | `GAMEOVER_TITLE` | `GAMEOVER_DESCRIPTION` | Marks `event_end` |
| Final | `FINAL_TITLE` | `FINAL_DESCRIPTION` | Marks `event_end` |
| Game Over: Tied | `GAMEOVERTIED_TITLE` | `GAMEOVERTIED_DESCRIPTION` | Marks `event_end` |
| Final: Tied | `FINALTIED_TITLE` | `FINALTIED_DESCRIPTION` | Marks `event_end` |

---

## At-Bat Event Message Format

At-bat events (playTypeActual == `atBat`) are formatted as:

```
```
<game_situation_block>
<pitch_count_prefix><play_description>
```
<emoji_line>
<end_of_inning_block_if_applicable>
```

### Game Situation Block

An ASCII art box score showing inning, base state, and team stats:

```
TOP  3   ┌───┬──┬──┬──┐
    ○      │HOU│  5│  7│  0│
  ○ ●    ├───┼──┼──┼──┤
3 Outs   │TEX│  3│  5│  1│
         └───┴──┴──┴──┘
```

Fields displayed:
- Inning half (TOP/BOT, 3 chars) + inning number (right-aligned 2 chars)
- Base occupancy: ● = occupied, ○ = empty (3rd base left of inning, 2nd above, 1st right)
- Out count left-aligned (e.g. "3 Outs", " 1  Out")
- Away team: abbreviation (3 chars, upper), runs, hits, errors
- Home team: abbreviation (3 chars, upper), runs, hits, errors

**Special case — bot catching up**: if the play's inning is behind the current linescore inning (API is still emitting plays from previous innings), the box score is replaced with a simplified block containing just the inning label and text "BOT BEHIND / CATCHING UP".

### Pitch Count Prefix

If `playType == 'atBat'`: `"On a {balls}-{strikes} count, "`  
Otherwise: `""` (empty)

### Emoji Line

Appended after the play description. Built by concatenating emoji characters:

| Condition | Emoji constant |
|-----------|---------------|
| Strikeout (swinging) by pitching team | `EMOTE_STRIKEOUT` repeated per K |
| Strikeout (called) by pitching team | `EMOTE_STRIKEOUT_LOOKING` repeated per called K |
| Home Run (non-grand-slam) | `EMOTE_HOMERUN` |
| Grand Slam (Home Run with 4 RBIs) | `EMOTE_GRAND_SLAM` |
| Each RBI | `EMOTE_RBI` |
| Each earned run (not RBI) | `EMOTE_EARNED_RUN` |
| Each unearned run | `EMOTE_UNEARNED_RUN` |

Strikeout tracker header: `"<PitchingTeamName> K Tracker (<total>): "`  
Strikeout emojis are accumulated across the entire game, reset each new game.

### End of Inning Block

Appended when `outs == "3"`:

```
```------ End of TOP  3 ------
<full_linescore_string>
------ End of TOP  3 ------

Current delay set to 30 seconds.```
```

If it is the end of the top of the 7th inning, a 7th-inning-stretch URL/message is appended after the block.

---

## Player Change Message Format

Non-at-bat events (pitching changes, substitutions, etc.) are formatted as:

```
```
<play_description>
```
<end_of_inning_block_if_applicable>
```

No game situation block or emoji line is included.

---

## Thread Creation Summary Format

When a new game thread is created, the parent message summary uses:

```
<discord_timestamp> | <away_flair> @ <home_flair>[ | Game <N>]
```

The thread name:
```
⚾ | <away_short> at <home_short>[ | Game <N>] | <YYYY-MM-DD>
```

Doubleheader suffix (`| Game N`) is omitted for single games.
