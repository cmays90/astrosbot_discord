"""
Unit tests for the due-up feature: cards.due_up_rows / cards.due_up_card and
their embedding (with headshots) in the end-of-inning card.
"""
import cards
from mocks.discord_mock import view_text


AWAY_ORDER = [1, 2, 3, 4, 5, 6, 7, 8, 9]
HOME_ORDER = [11, 12, 13, 14, 15, 16, 17, 18, 19]
AWAY_POS = ["CF", "SS", "2B", "1B", "DH", "LF", "RF", "3B", "C"]
HOME_POS = ["RF", "1B", "DH", "C", "3B", "LF", "CF", "SS", "2B"]


def _player(pid, name, pos):
    return {"ID{}".format(pid): {
        "person": {"id": pid, "fullName": name},
        "position": {"abbreviation": pos},
    }}


def _players(order, names, positions):
    out = {}
    for pid, nm, pos in zip(order, names, positions):
        out.update(_player(pid, nm, pos))
    return out


def _game(offense=None, away_pas=0, home_pas=0):
    away_names = ["Away{}".format(i) for i in range(1, 10)]
    home_names = ["Home{}".format(i) for i in range(1, 10)]
    plays = []
    for _ in range(away_pas):
        plays.append({"about": {"halfInning": "top"}, "result": {"description": "x"}})
    for _ in range(home_pas):
        plays.append({"about": {"halfInning": "bottom"}, "result": {"description": "x"}})
    # An in-progress (incomplete) play must not be counted.
    plays.append({"about": {"halfInning": "top"}, "result": {}})
    live = {
        "boxscore": {"teams": {
            "away": {"battingOrder": AWAY_ORDER,
                     "players": _players(AWAY_ORDER, away_names, AWAY_POS)},
            "home": {"battingOrder": HOME_ORDER,
                     "players": _players(HOME_ORDER, home_names, HOME_POS)},
        }},
        "linescore": {"offense": offense or {}},
        "plays": {"allPlays": plays},
    }
    return {"liveData": live}


def _thumbnail_urls(view):
    """Every Thumbnail media URL anywhere in a LayoutView."""
    urls = []

    def walk(item):
        media = getattr(item, "media", None)
        if media is not None:
            urls.append(getattr(media, "url", str(media)))
        accessory = getattr(item, "accessory", None)
        if accessory is not None:
            walk(accessory)
        for child in getattr(item, "children", []) or []:
            walk(child)

    for child in getattr(view, "children", []) or []:
        walk(child)
    return urls


def test_offense_path_uses_batter_ondeck_inhole():
    offense = {
        "batter": {"id": 3, "fullName": "Away3"},
        "onDeck": {"id": 4, "fullName": "Away4"},
        "inHole": {"id": 5, "fullName": "Away5"},
    }
    # (slot, name, pos, person_id) — slots come from the away batting order.
    assert cards.due_up_rows(_game(offense=offense)) == [
        (3, "Away3", "2B", 3),
        (4, "Away4", "1B", 4),
        (5, "Away5", "DH", 5),
    ]


def test_offense_path_none_until_data_present():
    # Missing onDeck/inHole -> not ready yet.
    offense = {"batter": {"id": 1, "fullName": "Away1"}}
    assert cards.due_up_rows(_game(offense=offense)) is None
    assert cards.due_up_card(_game(offense=offense)) is None


def test_side_path_counts_completed_plate_appearances():
    # Away has completed 3 PAs -> next up is slot 4, then 5, 6.
    rows = cards.due_up_rows(_game(away_pas=3), side="away")
    assert [r[0] for r in rows] == [4, 5, 6]
    assert [r[1] for r in rows] == ["Away4", "Away5", "Away6"]
    # The incomplete play was not counted (otherwise start would shift).


def test_side_path_wraps_around_the_order():
    # 8 completed -> slot 9, then wraps to slot 1, slot 2.
    rows = cards.due_up_rows(_game(home_pas=8), side="home")
    assert [r[0] for r in rows] == [9, 1, 2]
    assert [r[1] for r in rows] == ["Home9", "Home1", "Home2"]


def test_side_path_none_without_full_order():
    g = _game()
    g["liveData"]["boxscore"]["teams"]["away"]["battingOrder"] = [1, 2, 3]
    assert cards.due_up_rows(g, side="away") is None


def test_due_up_card_renders_with_headshots():
    offense = {
        "batter": {"id": 1, "fullName": "Away1"},
        "onDeck": {"id": 2, "fullName": "Away2"},
        "inHole": {"id": 3, "fullName": "Away3"},
    }
    view = cards.due_up_card(_game(offense=offense))
    text = view_text(view)
    assert "Due up" in text
    assert "**Away1**" in text and "CF" in text
    # Each batter carries a headshot thumbnail keyed by their person id.
    urls = _thumbnail_urls(view)
    assert all(cards.player_headshot_url(pid) in urls for pid in (1, 2, 3))


def test_end_of_inning_card_embeds_due_up_with_headshot():
    info = {
        "inningHalf": "top", "inning": "5",
        "fullLinescoreString": "linescore",
        "pitcherCount": None,
        "dueUp": [(1, "Home1", "RF", 11)],
    }
    view = cards.end_of_inning_card(info)
    text = view_text(view)
    assert "Due up" in text
    assert "**Home1**" in text
    assert cards.player_headshot_url(11) in _thumbnail_urls(view)


def test_end_of_inning_card_without_due_up():
    info = {"inningHalf": "bottom", "inning": "3", "fullLinescoreString": "ls",
            "pitcherCount": None}
    text = view_text(cards.end_of_inning_card(info))
    assert "Due up" not in text


# --------------------------------------------------------------------------- #
# "Now up" on the at-bat card
# --------------------------------------------------------------------------- #


def test_now_up_row_reads_offense_batter():
    offense = {"batter": {"id": 4, "fullName": "Away4"}}
    assert cards.now_up_row(_game(offense=offense)) == ("Away4", "1B", 4)


def test_now_up_row_none_without_batter():
    assert cards.now_up_row(_game()) is None


def _atbat_info(outs, now_up):
    return {
        "event": "Single", "inningHalf": "top", "inning": "5",
        "balls": "1", "strikes": "2", "outs": outs,
        "description": "Player singles on a line drive.",
        "funEmoji": "",
        "manOnFirst": False, "manOnSecond": False, "manOnThird": False,
        "awayTeamAbbv": "HOU", "homeTeamAbbv": "DET",
        "awayStats_linescore": {"runs": 1, "hits": 4, "errors": 0},
        "homeStats_linescore": {"runs": 0, "hits": 2, "errors": 1},
        "batterId": 100,
        "nowUp": now_up,
    }


def test_atbat_card_shows_now_up_mid_inning():
    view = cards.atbat_card(_atbat_info("1", ("Away5", "DH", 5)))
    text = view_text(view)
    assert "Now up:" in text and "Away5" in text and "DH" in text
    assert cards.player_headshot_url(5) in _thumbnail_urls(view)


def test_atbat_card_hides_now_up_at_third_out():
    view = cards.atbat_card(_atbat_info("3", ("Away5", "DH", 5)))
    text = view_text(view)
    assert "Now up" not in text


def test_atbat_card_without_now_up_data():
    info = _atbat_info("2", None)
    text = view_text(cards.atbat_card(info))
    assert "Now up" not in text
