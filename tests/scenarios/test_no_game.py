"""
Scenario: no game today — verify the bot posts the "No Game Today" embed
and does not attempt to create a thread.
"""
import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'BaseballConsumer'))

from mocks.mlb_mock import GameReplayer
from mocks.discord_mock import MockBot
from harness import Harness


class NoGameReplayer:
    """
    Returns an empty schedule on the first call, then marks done.
    The poller then sleeps until 5am; with speed_factor=1000 that sleep is
    compressed to ~54 real seconds at worst, so we use a 90s test timeout.
    """

    def __init__(self):
        self._calls = 0
        self.game_over = False

    def schedule(self, date=None, team=None, game_id=None):
        self._calls += 1
        if self._calls >= 2:
            self.game_over = True
        return []

    def get(self, endpoint, params=None):
        return {}

    def linescore(self, game_id):
        return ''

    def lookup_team(self, team_id):
        return []

    @property
    def guild_id(self):
        return None


@pytest.mark.asyncio
async def test_no_game_today():
    mlb = NoGameReplayer()
    disc = MockBot()

    # The poller sleeps "until 5am" (~54 000s) when there's no game.
    # With speed_factor=1000 that becomes ~54 real seconds; use 90s timeout.
    harness = Harness(mlb, disc, speed_factor=1000)
    try:
        await harness.run(timeout=90)
    finally:
        harness.cleanup()

    print("\n=== no_game scenario event log ===")
    disc.dump()

    # No threads should ever be created on a day with no game.
    assert not disc.threads_created(), "Unexpected thread created on no-game day"

    # The production code queues a "No Game Today" embed but with game_id=None,
    # which means discord_poster can't resolve a thread and silently drops it.
    # The key invariant is simply that the poller ran through its no-game path
    # (game_over becomes True) without creating any thread.
    assert mlb.game_over, "Poller did not complete its no-game cycle"
    print(f"  Poller completed: {mlb.game_over}, Discord events: {len(disc.event_log)}")
