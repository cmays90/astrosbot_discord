"""
Mock MLB Stats API for the test harness.

GameReplayer replays a recorded fixture (or a synthetic minimal one) through
the same statsapi interface the bot calls.  It advances the game state on
every schedule() call so the bot sees the natural Scheduled → Pre-Game →
Warmup → In Progress → Game Over → Final progression.
"""
import copy
import json
import sys
import os
from contextlib import contextmanager
from typing import Optional


# --------------------------------------------------------------------------- #
#  GameReplayer                                                                #
# --------------------------------------------------------------------------- #

class GameReplayer:
    """
    Replays a recorded game fixture one phase at a time.

    Phase order (each = one schedule() call from the bot):
      Scheduled  ×  scheduled_polls
      Pre-Game   ×  1
      Warmup     ×  1
      In Progress × ceil(total_plays / plays_per_poll)
      Game Over  ×  1
      Final      ×  1   ← sets self.game_over = True

    After Final the replayer keeps returning Final so the bot loop can
    drain cleanly before the harness cancels tasks.
    """

    def __init__(
        self,
        fixture_path: Optional[str] = None,
        fixture_data: Optional[dict] = None,
        scheduled_polls: int = 1,
        plays_per_poll: int = 5,
    ):
        if fixture_path:
            with open(fixture_path) as f:
                self.fixture = json.load(f)
        elif fixture_data:
            self.fixture = fixture_data
        else:
            raise ValueError("Provide fixture_path or fixture_data")

        self.scheduled_polls = scheduled_polls
        self.plays_per_poll = plays_per_poll
        self._schedule_calls = 0
        self.game_over = False
        self._all_plays: list = self.fixture['plays']

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _current_status(self) -> str:
        n = self._schedule_calls
        if n < self.scheduled_polls:
            return 'Scheduled'
        offset = n - self.scheduled_polls
        if offset == 0:
            return 'Pre-Game'
        if offset == 1:
            return 'Warmup'
        total_ip = max(1, -(-len(self._all_plays) // self.plays_per_poll))  # ceil div
        ip_call = offset - 2
        if ip_call < total_ip:
            return 'In Progress'
        if ip_call == total_ip:
            return 'Game Over'
        return 'Final'

    def _in_progress_call_index(self) -> int:
        """0-based index of the current In Progress poll."""
        return self._schedule_calls - self.scheduled_polls - 2

    # Optional fields the final card reads off the schedule dict; passed through
    # from the fixture when a captured real game provides them.
    _SCHEDULE_PASSTHROUGH = (
        'away_name', 'home_name', 'away_score', 'home_score',
        'winning_pitcher', 'losing_pitcher', 'save_pitcher',
        'venue_name', 'series_status',
    )

    def _schedule_item(self, status: str) -> list:
        info = self.fixture['game_info']
        item = {
            'game_id': info['game_id'],
            'game_date': info['game_date'],
            'game_datetime': info['game_datetime'],
            'status': status,
            'away_id': info['away_id'],
            'home_id': info['home_id'],
            'game_num': info.get('game_num', 1),
            'doubleheader': info.get('doubleheader', 'N'),
        }
        for k in self._SCHEDULE_PASSTHROUGH:
            if k in info:
                item[k] = info[k]
        return [item]

    # ------------------------------------------------------------------ #
    #  statsapi surface                                                    #
    # ------------------------------------------------------------------ #

    def schedule(self, date=None, team=None, game_id=None):
        """Called for both the poller (date+team) and discord_poster (game_id)."""
        status = self._current_status()
        self._schedule_calls += 1
        if status == 'Final':
            self.game_over = True
        return self._schedule_item(status)

    def get(self, endpoint: str, params: Optional[dict] = None):
        """Returns a game snapshot with allPlays sliced up to current poll."""
        if endpoint != 'game':
            return {}
        idx = self._in_progress_call_index()
        plays_so_far = min(len(self._all_plays), (idx + 1) * self.plays_per_poll)
        game_data = copy.deepcopy(self.fixture['game_data'])
        game_data['liveData']['plays']['allPlays'] = self._all_plays[:plays_so_far]
        return game_data

    def linescore(self, game_id):
        return self.fixture.get('linescore_string', '')

    def lookup_team(self, team_id):
        info = self.fixture['game_info']
        if str(team_id) == str(info['home_id']):
            return [self.fixture['home_team']]
        return [self.fixture['away_team']]

    # ------------------------------------------------------------------ #
    #  Context manager — patches statsapi in the bot modules              #
    # ------------------------------------------------------------------ #

    @contextmanager
    def patch(self):
        """
        Replace statsapi in every already-imported bot module with this
        replayer, restoring the originals on exit.
        """
        targets = {}
        for mod_name in ('BaseballConsumerV2', 'MainEntryBot'):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, 'statsapi'):
                targets[mod_name] = (mod, mod.statsapi)
                mod.statsapi = self
        try:
            yield self
        finally:
            for _name, (mod, original) in targets.items():
                mod.statsapi = original


# --------------------------------------------------------------------------- #
#  Minimal synthetic fixture (no recording needed for quick tests)            #
# --------------------------------------------------------------------------- #

def build_minimal_fixture(
    game_id: int = 748532,
    home_id: int = 117,
    away_id: int = 145,
    num_plays: int = 12,
) -> dict:
    """
    Returns a fixture dict suitable for GameReplayer(fixture_data=...).
    Uses synthetic play data so no real MLB API call is needed.
    """
    plays = []
    for i in range(num_plays):
        inning = (i // 6) + 1
        half = 'top' if (i % 6) < 3 else 'bottom'
        outs = (i % 3) + 1
        home_runs = i // 5
        away_runs = i // 7
        plays.append({
            'result': {
                'description': f'Play {i}: Flyout to center field.',
                'event': 'Flyout',
                'homeScore': home_runs,
                'awayScore': away_runs,
                'rbi': 0,
                'type': 'atBat',
            },
            'about': {
                'startTime': f'2025-06-04T19:{10 + i:02d}:00Z',
                'inning': inning,
                'halfInning': half,
                'atBatIndex': i,
            },
            'count': {'balls': 3, 'strikes': 2, 'outs': outs},
            'matchup': {
                'pitcher': {
                    'id': 700001 if half == 'top' else 700002,
                    'fullName': 'Home Starter' if half == 'top' else 'Away Starter',
                },
            },
            'runners': [],
        })

    linescore = {
        'outs': 2,
        'teams': {
            'home': {'runs': plays[-1]['result']['homeScore'], 'hits': 7, 'errors': 0, 'leftOnBase': 5},
            'away': {'runs': plays[-1]['result']['awayScore'], 'hits': 4, 'errors': 1, 'leftOnBase': 3},
        },
        'currentInning': plays[-1]['about']['inning'],
        'inningState': 'End',
        'inningHalf': 'Bottom',
    }

    boxscore = {
        'teams': {
            'home': {
                'team': {'abbreviation': 'HOU'},
                'pitchers': [700001],
                'players': {
                    'ID700001': {
                        'person': {'fullName': 'Home Starter'},
                        'stats': {'pitching': {'balls': 12, 'strikes': 31, 'pitchesThrown': 43}},
                    },
                },
            },
            'away': {
                'team': {'abbreviation': 'CWS'},
                'pitchers': [700002],
                'players': {
                    'ID700002': {
                        'person': {'fullName': 'Away Starter'},
                        'stats': {'pitching': {'balls': 9, 'strikes': 27, 'pitchesThrown': 36}},
                    },
                },
            },
        },
    }

    return {
        'game_info': {
            'game_id': game_id,
            'game_date': '2025-06-04',
            'game_datetime': '2025-06-04T19:10:00+00:00',
            'home_id': home_id,
            'away_id': away_id,
            'game_num': 1,
            'doubleheader': 'N',
        },
        'plays': plays,
        'game_data': {
            'liveData': {
                'plays': {'allPlays': plays},
                'linescore': linescore,
                'boxscore': boxscore,
            }
        },
        'linescore_string': (
            'HOU  0 0 0  1 0 0  2 0 0 | 3  7  0\n'
            'CWS  0 0 1  0 0 0  0 0 0 | 1  4  1'
        ),
        'home_team': {
            'id': home_id,
            'name': 'Houston Astros',
            'teamName': 'Astros',
            'shortName': 'HOU',
            'fileCode': 'hou',
        },
        'away_team': {
            'id': away_id,
            'name': 'Chicago White Sox',
            'teamName': 'White Sox',
            'shortName': 'CWS',
            'fileCode': 'cws',
        },
    }
