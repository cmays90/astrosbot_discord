"""
Scenario: the start-of-day thread-starter post is a rich pregame card.

Verifies that when a game is first seen (Scheduled), the channel message the
thread hangs from is a Components V2 card carrying the matchup, probables,
records, and venue — not a bare text line.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'BaseballConsumer'))

from mocks.mlb_mock import build_minimal_fixture
from mocks.discord_mock import MockBot
from harness import Harness

ASTROS = 117
TIGERS = 116


class ThreadStarterReplayer:
    """Scheduled on the first call, then Final to end the run. Serves rich
    schedule fields + a gameData.records payload for the pregame card."""

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
            'away_id': ASTROS,
            'home_id': TIGERS,
            'away_name': 'Houston Astros',
            'home_name': 'Detroit Tigers',
            'game_num': 1,
            'doubleheader': 'N',
            'away_probable_pitcher': 'Framber Valdez',
            'away_pitcher_note': '7-4, 2.91 ERA',
            'home_probable_pitcher': 'Tarik Skubal',
            'home_pitcher_note': '9-2, 2.15 ERA',
            'venue_name': 'Comerica Park',
            'national_broadcasts': ['ESPN'],
            'series_status': 'Game 2 of 3',
        }]

    def schedule(self, date=None, team=None, game_id=None):
        self._calls += 1
        if self._calls == 1:
            return self._item('Scheduled')
        self.game_over = True
        return self._item('Final')

    def get(self, endpoint, params=None):
        if endpoint == 'schedule':
            # seriesStatus lookup for the pregame card's series line.
            return {'dates': [{'games': [{'seriesStatus': {
                'gameNumber': 2, 'wins': 1, 'losses': 0, 'isTied': False,
                'winningTeam': {'id': ASTROS},
            }}]}]}
        # Records lookup ('game' endpoint) for the pregame card.
        return {'gameData': {'teams': {
            'away': {'record': {'wins': 45, 'losses': 32, 'divisionRank': '1'}},
            'home': {'record': {'wins': 38, 'losses': 39, 'divisionRank': '3'}},
        }}}

    def linescore(self, game_id):
        return ''

    def lookup_team(self, team_id):
        info = self._fixture['game_info']
        if str(team_id) == str(info['home_id']):
            return [self._fixture['home_team']]
        return [self._fixture['away_team']]


@pytest.mark.asyncio
async def test_thread_starter_is_pregame_card():
    mlb = ThreadStarterReplayer()
    disc = MockBot()

    harness = Harness(mlb, disc, speed_factor=1000)
    try:
        await harness.run(timeout=15)
    finally:
        harness.cleanup()

    print("\n=== thread-starter scenario event log ===")
    disc.dump()

    # The thread must have been created from the starter message.
    assert disc.threads_created(), "Expected a game thread to be created"

    # The thread-starter is a channel message (no thread_id) carrying a view.
    starters = [
        e for e in disc.event_log
        if e['type'] == 'message_sent' and 'channel_id' in e and e.get('has_view')
    ]
    assert starters, "Expected the thread-starter to be a Components V2 card"
    text = starters[0]['view_text']
    assert 'Houston Astros @' in text and 'Detroit Tigers' in text
    assert 'Framber Valdez' in text and 'Tarik Skubal' in text
    assert '45-32 (1)' in text and '38-39 (3)' in text
    assert 'Comerica Park' in text
    assert 'up 1-0' in text  # formatted series line
