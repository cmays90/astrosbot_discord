"""
Scenario: game is postponed — verify the Postponed embed fires.
"""
import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'BaseballConsumer'))

from mocks.mlb_mock import GameReplayer, build_minimal_fixture
from mocks.discord_mock import MockBot
from harness import Harness


class PostponedReplayer:
    """
    Serves Scheduled on the first call, then Postponed, then marks done.
    Re-uses build_minimal_fixture for team/game metadata.
    """

    def __init__(self):
        self._calls = 0
        self.game_over = False
        self._fixture = build_minimal_fixture()

    def _item(self, status):
        info = self._fixture['game_info']
        return [{
            'game_id': info['game_id'],
            'game_date': info['game_date'],
            'game_datetime': info['game_datetime'],
            'status': status,
            'away_id': info['away_id'],
            'home_id': info['home_id'],
            'game_num': 1,
            'doubleheader': 'N',
        }]

    def schedule(self, date=None, team=None, game_id=None):
        self._calls += 1
        if self._calls == 1:
            return self._item('Scheduled')
        self.game_over = True
        return self._item('Postponed')

    def get(self, endpoint, params=None):
        return {}

    def linescore(self, game_id):
        return ''

    def lookup_team(self, team_id):
        info = self._fixture['game_info']
        if str(team_id) == str(info['home_id']):
            return [self._fixture['home_team']]
        return [self._fixture['away_team']]


@pytest.mark.asyncio
async def test_postponed():
    mlb = PostponedReplayer()
    disc = MockBot()

    harness = Harness(mlb, disc, speed_factor=1000)
    try:
        await harness.run(timeout=15)
    finally:
        harness.cleanup()

    print("\n=== postponed scenario event log ===")
    disc.dump()

    # A thread must be created (Scheduled fires first).
    assert disc.threads_created(), "Expected game thread created on Scheduled status"

    # A Postponed card (Components V2 view) should have been sent to the thread.
    card_msgs = [
        e for e in disc.event_log
        if e['type'] == 'message_sent' and e.get('has_view') and 'thread_id' in e
    ]
    assert card_msgs, "Expected a Postponed card in the game thread"
    assert any('Game cancelled' in e.get('view_text', '') for e in card_msgs), \
        "Expected the Postponed card to carry the postponed copy"
    print(f"  Thread cards: {len(card_msgs)}")
