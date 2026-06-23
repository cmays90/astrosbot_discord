#!/usr/bin/env python
"""Replay a captured game fixture onto a real Discord TEST server.

    venv/bin/python scripts/replay_to_discord.py fixtures/game_776248.json \
        [--speed 50] [--plays-per-poll 5] [--timeout 600]

Reads connection info from discordSettings.test.doNotUpload.json (same schema
as discordSettings.doNotUpload.json, but pointing at a dedicated TEST guild and
channels — keep it out of git). This drives the bot's posting pipeline only
(threads, scheduled event, status/at-bat/final cards); it does not register
slash commands.

SAFETY: point the test settings at a throwaway server/channels, and do not run
your production bot with the same token at the same time (two gateway sessions
on one token is messy). Ideally use a separate bot application/token for tests.
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests'))

from mocks.mlb_mock import GameReplayer          # noqa: E402
from harness import Harness, RealDiscordBackend  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('fixture', help='path to a fixture JSON from capture_game.py')
    ap.add_argument('--settings', default='discordSettings.test.doNotUpload.json')
    ap.add_argument('--speed', type=float, default=50,
                    help='sleep speed-up factor (1 = real time; higher = faster)')
    ap.add_argument('--plays-per-poll', type=int, default=5)
    ap.add_argument('--timeout', type=float, default=600,
                    help='max wall-clock seconds before the run is cancelled')
    args = ap.parse_args()

    mlb = GameReplayer(fixture_path=args.fixture, plays_per_poll=args.plays_per_poll)
    disc = RealDiscordBackend(args.settings)
    asyncio.run(Harness(mlb, disc, speed_factor=args.speed).run(timeout=args.timeout))
    print("Replay finished.")


if __name__ == '__main__':
    main()
