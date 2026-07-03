"""Rich Discord message builders (Components V2 / UI Kit).

Every game post is rendered as a ``discord.ui.LayoutView`` here so the bot loop
stays readable and all the V2 boilerplate lives in one place. Builders return a
LayoutView ready to pass to ``channel.send(view=...)``.

A Components V2 message cannot also carry ``content``/``embed``; where a link
preview is still wanted (e.g. a win GIF) the caller enqueues a separate ``msg``.
"""

import datetime
import json
import logging
import os

import BaseballConsumerConstants as constants
import discord
from discord import ui

logger = logging.getLogger(__name__)

TEAMS_FILE = "./teams.json"
BASES_DIR = os.path.join(os.path.dirname(__file__), "assets", "bases")
BASES_ATTACHMENT = "bases.png"  # attachment filename referenced by at-bat cards

# Accent colors, chosen by meaning rather than sequence.
ASTROS_ORANGE = 0xEB6E1F
ASTROS_NAVY = 0x002D62
WIN_GREEN = 0x2E7D32
LOSS_RED = 0xC0392B
TIE_AMBER = 0xF39C12
RAIN_SLATE = 0x546E7A
NEUTRAL = ASTROS_NAVY

# Game statuses that represent a finished game (routed to final_card).
FINAL_STATES = {
    "Game Over",
    "Final",
    "Game Over: Tied",
    "Final: Tied",
    "Completed Early: Rain",
}

_teams_cache = None


def _teams():
    global _teams_cache
    if _teams_cache is None:
        try:
            with open(TEAMS_FILE) as f:
                _teams_cache = json.load(f)
        except Exception:
            logger.exception("Could not load %s", TEAMS_FILE)
            _teams_cache = {}
    return _teams_cache


def team_logo_url(team_id):
    """Raster PNG spot logo Discord can render as a thumbnail."""
    return "https://midfield.mlbstatic.com/v1/team/{}/spots/96".format(team_id)


def player_headshot_url(person_id):
    return "https://midfield.mlbstatic.com/v1/people/{}/spots/120".format(person_id)


def team_color(team_id, default=NEUTRAL):
    t = _teams().get(str(team_id), {})
    c = t.get("color")
    if isinstance(c, int):
        return c
    if isinstance(c, str):
        try:
            return int(c.lstrip("#"), 16)
        except ValueError:
            return default
    return default


def team_flair(team_id):
    return _teams().get(str(team_id), {}).get("flair", "")


def _layout(*items):
    view = ui.LayoutView(timeout=None)
    for it in items:
        view.add_item(it)
    return view


def _text(container, content):
    """Add a TextDisplay only when there's something to show."""
    if content:
        container.add_item(ui.TextDisplay(content))


# --------------------------------------------------------------------------- #
# Status cards
# --------------------------------------------------------------------------- #


def status_card(game, title, description, body="", *, accent=None, image_url=None):
    """Generic status post: heading + home-team logo, description, body, image."""
    home_id = game.get("home_id")
    away_id = game.get("away_id")
    if accent is None:
        accent = team_color(home_id) if home_id is not None else NEUTRAL
    c = ui.Container(accent_colour=accent)

    head = []
    if title:
        head.append("## {}".format(title))
    matchup = "{} {} @ {} {}".format(
        team_flair(away_id),
        game.get("away_name", ""),
        team_flair(home_id),
        game.get("home_name", ""),
    ).strip()
    if matchup:
        head.append("-# {}".format(matchup))
    heading = "\n".join(head) or "## Update"

    if home_id is not None:
        c.add_item(
            ui.Section(heading, accessory=ui.Thumbnail(media=team_logo_url(home_id)))
        )
    else:
        c.add_item(ui.TextDisplay(heading))

    _text(c, description)
    _text(c, body)
    if image_url:
        c.add_item(ui.MediaGallery(discord.MediaGalleryItem(media=image_url)))
    return _layout(c)


def no_game_card():
    c = ui.Container(accent_colour=RAIN_SLATE)
    if constants.NO_GAME_STATUS_TITLE:
        c.add_item(ui.TextDisplay("## {}".format(constants.NO_GAME_STATUS_TITLE)))
    _text(c, constants.NO_GAME_STATUS_DESCRIPTION)
    if not c.children:
        c.add_item(ui.TextDisplay("No game today."))
    return _layout(c)


def _start_timestamp(game):
    """Unix timestamp for the game's start, or None if unparseable."""
    raw = game.get("game_datetime")
    if not raw:
        return None
    try:
        return int(datetime.datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z").timestamp())
    except (ValueError, TypeError):
        return None


def _record_blurb(rec):
    """`45-32 (1st)` from a record dict, or '' if incomplete."""
    if not rec:
        return ""
    wins, losses = rec.get("wins"), rec.get("losses")
    if wins is None or losses is None:
        return ""
    rank = rec.get("divisionRank")
    return "{}-{}{}".format(wins, losses, " ({})".format(rank) if rank else "")


_HAND_LABELS = {"R": "RHP", "L": "LHP"}


def _pitcher_stat_note(stats):
    """`RHP, 7-4, 2.91 ERA, 15 GS` from a pitcher stat dict, or '' if empty.

    ``stats`` holds whichever of ``hand``/``wins``/``losses``/``era``/
    ``games_started`` were resolved; any may be missing.
    """
    if not stats:
        return ""
    parts = []
    hand = stats.get("hand")
    if hand:
        parts.append(_HAND_LABELS.get(hand, hand))
    wins, losses = stats.get("wins"), stats.get("losses")
    if wins is not None and losses is not None:
        parts.append("{}-{}".format(wins, losses))
    era = stats.get("era")
    if era is not None:
        parts.append("{} ERA".format(era))
    gs = stats.get("games_started")
    if gs is not None:
        parts.append("{} GS".format(gs))
    return ", ".join(parts)


def _probable_line(flair, name, stats):
    """`<:HOU:> Framber Valdez (LHP, 7-4, 2.91 ERA, 15 GS)`, or None when no
    starter set. ``stats`` is a per-pitcher dict, see ``_pitcher_stat_note``."""
    name = (name or "").strip()
    if not name or name.upper() == "TBD":
        return None
    line = "{} {}".format(flair, name).strip()
    note = _pitcher_stat_note(stats)
    if note:
        line = "{} ({})".format(line, note)
    return line


def format_series(series_status):
    """Friendly series-standing line for the pregame card.

    Returns one of: ``"First game of series"``, ``"Series tied X-X"``, or
    ``"<:leader_flair:> up X-Y"`` — or ``None`` if there's nothing to show.

    ``series_status`` is the standing *entering* the upcoming game, which
    ``_fetch_series_status`` derives from the **previous** game's statsapi
    ``seriesStatus`` (the upcoming game's own entry is always 0-0/tied until it
    is played). It is either the ``{"firstGame": True}`` marker or a played
    game's ``seriesStatus`` dict (``wins``/``losses``/``isTied``/``winningTeam``/
    ``result``). ``wins``/``losses`` are leader-relative (``wins`` ≥ ``losses``).
    """
    if not series_status:
        return None
    if series_status.get("firstGame"):
        return "First game of series"
    wins = series_status.get("wins") or 0
    losses = series_status.get("losses") or 0
    if series_status.get("isTied") or wins == losses:
        if wins == 0:
            # A played game can't leave the series 0-0; treat it as missing
            # data and omit the line rather than assert a bogus "tied 0-0".
            return None
        return "Series tied {0}-{0}".format(wins)
    leader = (series_status.get("winningTeam") or {}).get("id")
    flair = team_flair(leader) if leader is not None else ""
    if flair:
        return "{} up {}-{}".format(flair, max(wins, losses), min(wins, losses))
    # No flair to render — fall back to the API's ready-made phrasing,
    # e.g. "MIN leads 1-0" / "HOU wins 3-1".
    return series_status.get("result")


def pregame_card(game, our_team_id=None, records=None, series=None, pitcher_stats=None):
    """Marquee start-of-day card used as the game thread's starter message.

    Driven off the ``statsapi.schedule`` dict; ``records`` (optional) is
    ``{'home': {...}, 'away': {...}}`` of record dicts for the W-L line, and
    ``series`` (optional) is a statsapi ``seriesStatus`` dict for the friendly
    series line (falls back to the raw ``series_status`` string). The opponent
    (non-``our_team_id`` side) drives the logo and accent so each matchup card
    is visually distinct. ``pitcher_stats`` (optional) is ``{'home': {...},
    'away': {...}}`` of ``hand``/``wins``/``losses``/``era``/``games_started``
    for each side's probable starter, shown alongside their name.
    """
    home_id = game.get("home_id")
    away_id = game.get("away_id")
    opp_id = away_id if home_id == our_team_id else home_id
    if opp_id is None:
        opp_id = home_id

    c = ui.Container(accent_colour=team_color(opp_id))

    # Heading: matchup + opponent logo thumbnail.
    matchup = "## {} {} @ {} {}".format(
        team_flair(away_id),
        game.get("away_name", "Away"),
        team_flair(home_id),
        game.get("home_name", "Home"),
    ).strip()
    if game.get("doubleheader", "N") != "N" and game.get("game_num"):
        matchup = "{} | Game {}".format(matchup, game["game_num"])

    sub = []
    ts = _start_timestamp(game)
    if ts is not None:
        sub.append("<t:{0}:F> · <t:{0}:R>".format(ts))
    if records:
        rec_parts = []
        for side, tid in (("away", away_id), ("home", home_id)):
            blurb = _record_blurb(records.get(side))
            if blurb:
                rec_parts.append("{} {}".format(team_flair(tid), blurb).strip())
        if rec_parts:
            sub.append(" · ".join(rec_parts))
    heading = "\n".join([matchup] + sub)

    if opp_id is not None:
        c.add_item(
            ui.Section(heading, accessory=ui.Thumbnail(media=team_logo_url(opp_id)))
        )
    else:
        c.add_item(ui.TextDisplay(heading))

    # Probable pitchers.
    pitcher_stats = pitcher_stats or {}
    probables = [
        _probable_line(
            team_flair(away_id),
            game.get("away_probable_pitcher"),
            pitcher_stats.get("away"),
        ),
        _probable_line(
            team_flair(home_id),
            game.get("home_probable_pitcher"),
            pitcher_stats.get("home"),
        ),
    ]
    probables = [p for p in probables if p]
    if probables:
        c.add_item(ui.Separator())
        _text(c, "## ⚾ Probables\n{}".format("\n".join(probables)))

    # Venue / national TV / series context. national_broadcasts is a list.
    tv = game.get("national_broadcasts")
    if isinstance(tv, (list, tuple)):
        tv = ", ".join(tv)
    series_text = format_series(series) if series else game.get("series_status")
    meta = [m for m in (game.get("venue_name"), tv, series_text) if m]
    _text(c, " · ".join(meta) if meta else "")

    gid = game.get("game_id")
    if gid:
        c.add_item(
            ui.ActionRow(
                ui.Button(
                    label="Gameday", url="https://www.mlb.com/gameday/{}".format(gid)
                )
            )
        )
    return _layout(c)


def final_card(game, our_team_id):
    """Final-score card driven entirely off the statsapi.schedule dict."""
    home_id = game["home_id"]
    away_id = game["away_id"]
    home_score = game.get("home_score")
    away_score = game.get("away_score")

    try:
        hs, as_ = int(home_score), int(away_score)
    except (TypeError, ValueError):
        hs = as_ = None

    accent, result = NEUTRAL, "Final"
    if hs is not None:
        if our_team_id == home_id:
            our, opp = hs, as_
        elif our_team_id == away_id:
            our, opp = as_, hs
        else:
            our = opp = None
        if our is not None:
            if our > opp:
                accent, result = WIN_GREEN, "Astros win!"
            elif our < opp:
                accent, result = LOSS_RED, "Astros fall."
            else:
                accent, result = TIE_AMBER, "Tie ballgame."

    c = ui.Container(accent_colour=accent)
    score_line = "## {} {} {} — {} {} {}".format(
        team_flair(away_id),
        game.get("away_name", "Away"),
        away_score,
        home_score,
        game.get("home_name", "Home"),
        team_flair(home_id),
    )
    c.add_item(
        ui.Section(
            "{}\n-# {} · Final".format(score_line, result),
            accessory=ui.Thumbnail(media=team_logo_url(home_id)),
        )
    )

    c.add_item(ui.Separator())
    decisions = []
    if game.get("winning_pitcher"):
        decisions.append("**W:** {}".format(game["winning_pitcher"]))
    if game.get("losing_pitcher"):
        decisions.append("**L:** {}".format(game["losing_pitcher"]))
    if game.get("save_pitcher"):
        decisions.append("**SV:** {}".format(game["save_pitcher"]))
    _text(c, " · ".join(decisions))

    meta = [m for m in (game.get("venue_name"), game.get("series_status")) if m]
    _text(c, "-# {}".format(" · ".join(meta)) if meta else "")

    gid = game.get("game_id")
    if gid:
        c.add_item(
            ui.ActionRow(
                ui.Button(
                    label="Gameday", url="https://www.mlb.com/gameday/{}".format(gid)
                )
            )
        )
    return _layout(c)


# --------------------------------------------------------------------------- #
# Live play cards
# --------------------------------------------------------------------------- #


def _rhe_table(info):
    """R/H/E as a space-padded monospace code block, columns aligned (the
    header row reuses the exact column format so it lines up regardless of
    single- vs double-digit values)."""
    a = info["awayStats_linescore"]
    h = info["homeStats_linescore"]
    aw = info["awayTeamAbbv"].upper()[:3]
    hh = info["homeTeamAbbv"].upper()[:3]

    def row(label, runs, hits, errors):
        return "{:<3}{:>4}{:>4}{:>4}".format(label, runs, hits, errors)

    return "```\n{}\n{}\n{}\n```".format(
        row("", "R", "H", "E"),
        row(aw, a["runs"], a["hits"], a["errors"]),
        row(hh, h["runs"], h["hits"], h["errors"]),
    )


def bases_image_path(info):
    """Absolute path to the diamond PNG for this base state, or None if missing."""
    state = "{}{}{}".format(
        1 if info.get("manOnFirst") else 0,
        1 if info.get("manOnSecond") else 0,
        1 if info.get("manOnThird") else 0,
    )
    path = os.path.join(BASES_DIR, "bases_{}.png".format(state))
    return path if os.path.exists(path) else None


def atbat_card(info):
    is_hr = info.get("event", "") == "Home Run"
    accent = ASTROS_ORANGE if is_hr else NEUTRAL

    c = ui.Container(accent_colour=accent)
    half = info["inningHalf"].title()
    outs = info["outs"]

    # Section 1: inning / count / outs + the play, paired with the bases diamond.
    state = "### {} {}\n{}-{} count · {} {}".format(
        half,
        info["inning"],
        info["balls"],
        info["strikes"],
        outs,
        "out" if outs == "1" else "outs",
    )
    body = "{}\n\n{}".format(state, info["description"])
    fun = (info.get("funEmoji") or "").strip()
    if fun:
        body = "{}\n{}".format(body, fun)
    if bases_image_path(info):
        c.add_item(
            ui.Section(
                body, accessory=ui.Thumbnail(media="attachment://" + BASES_ATTACHMENT)
            )
        )
    else:
        c.add_item(ui.TextDisplay(body))

    # Section 2: the R/H/E table, paired with the batter's headshot.
    score = _rhe_table(info)
    batter_id = info.get("batterId")
    if batter_id:
        c.add_item(
            ui.Section(
                score, accessory=ui.Thumbnail(media=player_headshot_url(batter_id))
            )
        )
    else:
        c.add_item(ui.TextDisplay(score))

    # Who's at the plate now — only when this play ended a plate appearance
    # (not a challenge / timeout / other interruption), and skipped at the
    # third out, where the end-of-inning card carries the due-up instead.
    now_up = info.get("nowUp")
    if now_up and outs != "3" and info.get("endsPlateAppearance"):
        name, pos, pid = now_up
        label = "**Now up:** {}{}".format(name, " {}".format(pos) if pos else "")
        c.add_item(ui.Separator())
        c.add_item(
            ui.Section(label, accessory=ui.Thumbnail(media=player_headshot_url(pid)))
        )
    return _layout(c)


def player_change_card(info):
    c = ui.Container(accent_colour=NEUTRAL)
    c.add_item(ui.TextDisplay("\U0001f501 {}".format(info["description"])))
    return _layout(c)


def end_of_inning_card(info):
    c = ui.Container(accent_colour=NEUTRAL)
    half = info["inningHalf"].upper()[:3]
    c.add_item(ui.TextDisplay("### End of {} {}".format(half, info["inning"])))
    if info.get("fullLinescoreString"):
        c.add_item(ui.TextDisplay("```\n{}\n```".format(info["fullLinescoreString"])))
    pc = info.get("pitcherCount")
    if pc:
        c.add_item(
            ui.TextDisplay(
                "-# {} — {} pitches ({}-{})".format(pc[0], pc[3], pc[1], pc[2])
            )
        )
    if info.get("dueUp"):
        c.add_item(ui.Separator())
        c.add_item(ui.TextDisplay("**Due up**"))
        c.add_item(ui.TextDisplay(_due_up_block(info["dueUp"])))
    c.add_item(ui.TextDisplay("-# Current delay: {}s".format(constants.DELAY)))
    return _layout(c)


# --------------------------------------------------------------------------- #
# Command cards
# --------------------------------------------------------------------------- #


def lineup_card(game_data):
    """Both teams' batting orders, or None if either order isn't set yet."""
    boxscore = game_data.get("liveData", {}).get("boxscore", {})
    gdata_teams = game_data.get("gameData", {}).get("teams", {})

    c = ui.Container(accent_colour=ASTROS_NAVY)
    c.add_item(ui.TextDisplay("## Starting lineups"))
    for side in ("away", "home"):
        team = boxscore.get("teams", {}).get(side, {})
        order = team.get("battingOrder") or []
        if not order:
            return None
        players = team.get("players", {})
        team_obj = gdata_teams.get(side, {})
        team_id = team_obj.get("id")
        team_name = team_obj.get("name", side.title())

        rows = []  # (num, name, pos, slash, hr, rbi)
        for i, pid in enumerate(order, 1):
            p = players.get("ID{}".format(pid), {})
            name = p.get("person", {}).get("fullName", "TBD")
            pos = p.get("position", {}).get("abbreviation", "")
            b = p.get("seasonStats", {}).get("batting", {})
            slash = "/".join(
                str(b.get(k, ".---")) for k in ("avg", "obp", "slg", "ops")
            )
            rows.append((i, name, pos, slash, b.get("homeRuns", 0), b.get("rbi", 0)))

        width = max(len(r[1]) for r in rows)
        slash_w = max(len(r[3]) for r in rows)
        lines = "\n".join(
            "{}. {:<{w}} {:<2} | {:<{sw}} | {:>2} HR {:>3} RBI".format(
                n, name, pos, slash, hr, rbi, w=width, sw=slash_w
            )
            for (n, name, pos, slash, hr, rbi) in rows
        )
        block = "```\n{}\n```".format(lines)

        if side == "home":
            c.add_item(ui.Separator())
        header = "{} **{}**".format(team_flair(team_id), team_name).strip()
        if team_id is not None:
            c.add_item(
                ui.Section(header, accessory=ui.Thumbnail(media=team_logo_url(team_id)))
            )
        else:
            c.add_item(ui.TextDisplay(header))
        c.add_item(ui.TextDisplay(block))
    return _layout(c)


def _player_position(teams, pid):
    """Position abbreviation for a player id, looked up across both boxscores."""
    for s in ("away", "home"):
        p = teams.get(s, {}).get("players", {}).get("ID{}".format(pid))
        if p:
            return p.get("position", {}).get("abbreviation", "")
    return ""


def now_up_row(game_data):
    """The batter currently at the plate as (name, pos, person_id), or None.
    Stashed on info['nowUp'] so the at-bat card can show who's up next."""
    live = game_data.get("liveData", {})
    batter = live.get("linescore", {}).get("offense", {}).get("batter")
    if not batter:
        return None
    pid = batter.get("id")
    teams = live.get("boxscore", {}).get("teams", {})
    return (batter.get("fullName", "TBD"), _player_position(teams, pid), pid)


def _due_up_rows(game_data, side=None):
    """The next three batters as (slot, name, pos) tuples, or None if the data
    isn't available yet.

    side=None -> read linescore.offense (batter/onDeck/inHole): exactly the
        next three for whoever is at bat. Used by /due-up.
    side in {'home','away'} -> compute from that team's battingOrder and how
        many plate appearances it has completed. Used at end of inning, where
        linescore.offense may still point at the side that just finished.
    """
    live = game_data.get("liveData", {})
    teams = live.get("boxscore", {}).get("teams", {})

    def position_of(pid):
        return _player_position(teams, pid)

    def slot_of(pid):
        for s in ("away", "home"):
            order = teams.get(s, {}).get("battingOrder") or []
            if pid in order:
                return order.index(pid) + 1
        return None

    if side is None:
        offense = live.get("linescore", {}).get("offense", {})
        people = [offense.get("batter"), offense.get("onDeck"), offense.get("inHole")]
        if not all(people):
            return None
        return [
            (slot_of(person.get("id")), person.get("fullName", "TBD"),
             position_of(person.get("id")), person.get("id"))
            for person in people
        ]

    order = teams.get(side, {}).get("battingOrder") or []
    if len(order) < 9:
        return None
    plays = live.get("plays", {}).get("allPlays", []) or []
    completed = sum(
        1 for p in plays
        if ("away" if p.get("about", {}).get("halfInning") == "top" else "home") == side
        and "description" in p.get("result", {})
    )
    start = completed % 9
    players = teams.get(side, {}).get("players", {})
    rows = []
    for k in range(3):
        idx = (start + k) % 9
        pid = order[idx]
        p = players.get("ID{}".format(pid), {})
        rows.append((idx + 1,
                     p.get("person", {}).get("fullName", "TBD"),
                     p.get("position", {}).get("abbreviation", ""),
                     pid))
    return rows


def _due_up_block(rows):
    """Fenced ``#. Name Pos`` block, mirroring lineup_card's row style. Kept
    compact (no headshots) so the end-of-inning post stays small."""
    width = max(len(name) for _, name, _, _ in rows)
    lines = "\n".join(
        "{}. {:<{w}} {}".format(slot if slot else "-", name, pos, w=width).rstrip()
        for (slot, name, pos, _pid) in rows
    )
    return "```\n{}\n```".format(lines)


def due_up_rows(game_data, side=None):
    """The next three batters as (slot, name, pos, person_id) tuples, or None.
    Stashed on info['dueUp'] so the end-of-inning card can render the block."""
    return _due_up_rows(game_data, side)


def due_up_card(game_data, side=None):
    """`/due-up` view: the next three batters, or None if not available yet."""
    rows = _due_up_rows(game_data, side)
    if not rows:
        return None
    c = ui.Container(accent_colour=ASTROS_NAVY)
    c.add_item(ui.TextDisplay("## Due up"))
    c.add_item(ui.TextDisplay(_due_up_block(rows)))
    return _layout(c)


def pitchcount_card(entries):
    """entries: iterable of (label, name, balls, strikes, total)."""
    c = ui.Container(accent_colour=ASTROS_NAVY)
    c.add_item(ui.TextDisplay("## Pitch count"))
    for label, name, balls, strikes, total in entries:
        c.add_item(
            ui.TextDisplay(
                "**{}** {} — {} pitches ({}-{})".format(
                    label, name, total, balls, strikes
                )
            )
        )
    return _layout(c)
