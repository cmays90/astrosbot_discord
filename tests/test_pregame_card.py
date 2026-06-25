"""
Unit tests for cards.pregame_card — the start-of-day thread-starter card built
off the statsapi.schedule dict (+ optional records).
"""
import cards
from mocks.discord_mock import view_text

TEAM_ID = 117  # Astros (home in this fixture)
OPP_ID = 116   # Tigers


def _schedule(**overrides):
    game = {
        'game_id': 776248,
        'game_datetime': '2026-06-25T22:40:00+00:00',
        'game_date': '2026-06-25',
        'status': 'Scheduled',
        'away_id': TEAM_ID,
        'home_id': OPP_ID,
        'away_name': 'Houston Astros',
        'home_name': 'Detroit Tigers',
        'doubleheader': 'N',
        'game_num': 1,
        'away_probable_pitcher': 'Framber Valdez',
        'away_pitcher_note': '7-4, 2.91 ERA',
        'home_probable_pitcher': 'Tarik Skubal',
        'home_pitcher_note': '9-2, 2.15 ERA',
        'venue_name': 'Comerica Park',
        'national_broadcasts': ['ESPN', 'MLB.tv Free Game'],  # statsapi returns a list
        'series_status': 'Game 2 of 3',
    }
    game.update(overrides)
    return game


def _records():
    return {
        'away': {'wins': 45, 'losses': 32, 'divisionRank': '1'},
        'home': {'wins': 38, 'losses': 39, 'divisionRank': '3'},
    }


def _series(game_number, wins, losses, leader_id=None):
    s = {'gameNumber': game_number, 'wins': wins, 'losses': losses,
         'isTied': wins == losses}
    if leader_id is not None:
        s['winningTeam'] = {'id': leader_id}
    return s


def test_format_series_first_game():
    assert cards.format_series(_series(1, 0, 0)) == "First game of series"
    # gameNumber 1 wins even if counts somehow present.
    assert cards.format_series(_series(1, 0, 0, leader_id=OPP_ID)) == "First game of series"


def test_format_series_tied():
    assert cards.format_series(_series(3, 1, 1)) == "Series tied 1-1"


def test_format_series_leader():
    # Tigers (116) lead 2-1 entering game 4.
    out = cards.format_series(_series(4, 2, 1, leader_id=OPP_ID))
    assert out.endswith("up 2-1")
    assert cards.team_flair(OPP_ID) in out


def test_format_series_none():
    assert cards.format_series(None) is None
    assert cards.format_series({}) is None


def test_full_card_has_all_blocks():
    text = view_text(cards.pregame_card(
        _schedule(), TEAM_ID, records=_records(),
        series=_series(2, 1, 0, leader_id=TEAM_ID)))
    # Matchup heading with names.
    assert 'Houston Astros @' in text
    assert 'Detroit Tigers' in text
    # Start time as a Discord timestamp (absolute + relative).
    assert '<t:' in text and ':F>' in text and ':R>' in text
    # Records line.
    assert '45-32 (1)' in text
    assert '38-39 (3)' in text
    # Probables (team emoji + name + stats in parens).
    assert '{} Framber Valdez (7-4, 2.91 ERA)'.format(cards.team_flair(TEAM_ID)) in text
    assert '{} Tarik Skubal (9-2, 2.15 ERA)'.format(cards.team_flair(OPP_ID)) in text
    # Meta line.
    assert 'Comerica Park' in text
    assert 'ESPN, MLB.tv Free Game' in text  # list joined into one string
    assert 'up 1-0' in text  # formatted series line (HOU leads 1-0 entering game 2)


def test_opponent_drives_accent_and_logo():
    # Astros are away here; the opponent (home Tigers, 116) should be the logo.
    view = cards.pregame_card(_schedule(), TEAM_ID)
    container = view.children[0]
    accent = container.accent_colour
    assert getattr(accent, 'value', accent) == cards.team_color(OPP_ID)
    assert view_text(view)  # renders without error
    # The opponent logo URL appears somewhere in the view's thumbnails.
    urls = []

    def walk(item):
        media = getattr(item, 'media', None)
        if media is not None:
            urls.append(getattr(media, 'url', str(media)))
        accessory = getattr(item, 'accessory', None)
        if accessory is not None:
            walk(accessory)
        for child in getattr(item, 'children', []) or []:
            walk(child)
    for child in view.children:
        walk(child)
    assert any(str(OPP_ID) in u for u in urls)


def test_doubleheader_game_number():
    text = view_text(cards.pregame_card(_schedule(doubleheader='Y', game_num=2), TEAM_ID))
    assert 'Game 2' in text


def test_sparse_card_renders():
    """No probables, no records, no meta — still produces a clean card."""
    sparse = _schedule(
        away_probable_pitcher='TBD', away_pitcher_note='',
        home_probable_pitcher=None, home_pitcher_note=None,
        venue_name=None, national_broadcasts=None, series_status=None,
    )
    text = view_text(cards.pregame_card(sparse, TEAM_ID, records=None))
    assert 'Houston Astros @' in text
    assert 'Probables' not in text  # no probables block when both sides are TBD
