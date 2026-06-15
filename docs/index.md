# Baseball Game Thread Bot — Documentation Index

Implementation-agnostic specifications for rebuilding this system in any language or framework.

## Documents

| Document | Contents |
|----------|----------|
| [overview.md](overview.md) | System purpose, architecture, and key behaviors |
| [data-model.md](data-model.md) | Database schema, event ID construction, config file formats |
| [game-polling.md](game-polling.md) | Polling loop logic, adaptive scheduling, play processing, error handling |
| [message-formatting.md](message-formatting.md) | All message formats: game status, at-bat events, player changes, thread names |
| [chat-integration.md](chat-integration.md) | Chat platform requirements, thread lifecycle, queue schema, !delay command |
| [external-apis.md](external-apis.md) | MLB Stats API calls, field mappings, game status values, retry behavior |
| [configuration.md](configuration.md) | All configuration keys and tunable constants |

## Quick Reference

**Team ID (Houston Astros)**: 117  
**Database**: SQLite, single file  
**Concurrency model**: 3 async tasks sharing a message queue  
**Polling interval during live game**: 10 seconds  
**Default spoiler delay**: 30 seconds  
**Thread close delay after game**: 30 minutes  
