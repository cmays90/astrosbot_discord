"""
Unit tests for BaseballUpdaterBotV2.select_win_message — the custom WIN_MESSAGES
selection logic (string vs. array rotation, win/loss/not-involved/unset).
"""
import BaseballConsumerV2
from BaseballConsumerV2 import BaseballUpdaterBotV2

TEAM_ID = 117  # our team
OPP_ID = 108

def _bot(win_messages):
    bot = BaseballUpdaterBotV2()
    bot.TEAM_ID = TEAM_ID
    bot.WIN_MESSAGES = win_messages
    return bot

def _game(home_id, away_id, home_score, away_score, game_id=12345):
    return {
        'game_id': game_id,
        'home_id': home_id,
        'away_id': away_id,
        'home_score': home_score,
        'away_score': away_score,
    }


async def test_unset_returns_none():
    bot = _bot(None)
    assert await bot.select_win_message(_game(TEAM_ID, OPP_ID, 5, 3)) is None


async def test_string_message_on_home_win():
    bot = _bot("WE WON")
    assert await bot.select_win_message(_game(TEAM_ID, OPP_ID, 5, 3)) == "WE WON"


async def test_string_message_on_away_win():
    bot = _bot("WE WON")
    assert await bot.select_win_message(_game(OPP_ID, TEAM_ID, 2, 7)) == "WE WON"


async def test_loss_returns_none():
    bot = _bot("WE WON")
    assert await bot.select_win_message(_game(TEAM_ID, OPP_ID, 1, 4)) is None


async def test_tie_returns_none():
    bot = _bot("WE WON")
    assert await bot.select_win_message(_game(TEAM_ID, OPP_ID, 4, 4)) is None


async def test_team_not_in_game_returns_none():
    bot = _bot("WE WON")
    assert await bot.select_win_message(_game(OPP_ID, 109, 5, 3)) is None


async def test_array_rotates_by_season_game_number(monkeypatch):
    messages = ["zero", "one", "two"]
    bot = _bot(messages)

    def fake_get(endpoint, params):
        assert endpoint == 'game'
        return {'gameData': {'teams': {'home': {'record': {'gamesPlayed': 7}}}}}

    monkeypatch.setattr(BaseballConsumerV2.statsapi, 'get', fake_get)
    # 7 % 3 == 1
    assert await bot.select_win_message(_game(TEAM_ID, OPP_ID, 5, 3)) == "one"


async def test_array_uses_correct_side(monkeypatch):
    messages = ["zero", "one", "two"]
    bot = _bot(messages)

    def fake_get(endpoint, params):
        # away is our team; gamesPlayed 6 -> 6 % 3 == 0
        return {'gameData': {'teams': {'away': {'record': {'gamesPlayed': 6}}}}}

    monkeypatch.setattr(BaseballConsumerV2.statsapi, 'get', fake_get)
    assert await bot.select_win_message(_game(OPP_ID, TEAM_ID, 2, 7)) == "zero"


async def test_array_lookup_failure_falls_back(monkeypatch):
    messages = ["zero", "one"]
    bot = _bot(messages)

    def fake_get(endpoint, params):
        raise KeyError('boom')

    monkeypatch.setattr(BaseballConsumerV2.statsapi, 'get', fake_get)
    assert await bot.select_win_message(_game(TEAM_ID, OPP_ID, 5, 3)) is None
