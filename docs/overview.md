# Baseball Game Thread Bot — System Overview

## Purpose

An automated bot that monitors live MLB games for a configured team and posts real-time play-by-play updates into a chat platform (currently Discord). It manages the full game lifecycle: creating a dedicated discussion thread before the game, streaming live events during play, and closing the thread after the game ends.

## High-Level Architecture

The system has three concurrent components running in a loop:

```
┌─────────────────────┐      ┌────────────────┐      ┌─────────────────────┐
│  Game Data Poller   │─────▶│  Message Queue  │─────▶│   Chat Poster       │
│  (MLB Stats API)    │      │  (async FIFO)   │      │   (Discord)         │
└─────────────────────┘      └────────────────┘      └─────────────────────┘
                                                              │
                                                      ┌───────▼────────┐
                                                      │  Persistence   │
                                                      │  (SQLite DB)   │
                                                      └────────────────┘
```

1. **Game Data Poller** — polls the MLB Stats API on an adaptive schedule, detects new events, and enqueues messages.
2. **Message Queue** — decouples polling from posting; buffers messages so posting delays don't block polling.
3. **Chat Poster** — dequeues messages and sends them to the appropriate chat thread, managing thread creation and lifecycle.

## Key Behaviors

- Exactly-once event delivery: every event is assigned a deterministic ID and logged to the database; duplicates are skipped.
- Adaptive polling: the poll interval shrinks as a game becomes more active (scheduled → pre-game → in-progress → 10s).
- Configurable spoiler delay: server members can vote to add a delay (0–120 seconds) before events are posted.
- All MLB teams are tracked by numeric ID; the monitored team is configured at startup.
- The system self-recovers from transient API failures with exponential back-off.
