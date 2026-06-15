#!/usr/bin/env bash
set -euo pipefail

OUTPUT="astrosbot.tar.gz"

tar -czf "$OUTPUT" \
    BaseballConsumer/MainEntryBot.py \
    BaseballConsumer/BaseballConsumerV2.py \
    BaseballConsumer/BaseballConsumerConstants.py \
    BaseballConsumer/__init__.py \
    BaseballConsumer/logs/game_events.db \
    settings.json \
    discordSettings.doNotUpload.json \
    teams.json \
    requirements.txt \
    package.sh

echo "Created $OUTPUT"
tar -tvf "$OUTPUT"
