#!/usr/bin/env python
"""Capture a real (usually completed) MLB game into a GameReplayer fixture.

    venv/bin/python scripts/capture_game.py <gamePk> [out.json] [--max-plays N]

The fixture can then be replayed through the bot — offline (MockBot) or onto a
real test server (see scripts/replay_to_discord.py). Find a gamePk on the MLB
schedule, e.g. statsapi.schedule(date='2025-09-20', team=117)[0]['game_id'].
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'BaseballConsumer'))
import statsapi  # noqa: E402  (path set above)


def build_fixture(game_pk, max_plays=None):
    sched = statsapi.schedule(game_id=game_pk)[0]
    game = statsapi.get('game', {'gamePk': game_pk})
    plays = game['liveData']['plays']['allPlays']
    if max_plays:
        plays = plays[:max_plays]
        game['liveData']['plays']['allPlays'] = plays

    info = {
        'game_id': sched['game_id'],
        'game_date': sched['game_date'],
        'game_datetime': sched['game_datetime'],
        'home_id': sched['home_id'],
        'away_id': sched['away_id'],
        'game_num': sched.get('game_num', 1),
        'doubleheader': sched.get('doubleheader', 'N'),
    }
    # Pass through the fields the final + pregame cards render.
    for k in ('away_name', 'home_name', 'away_score', 'home_score',
              'winning_pitcher', 'losing_pitcher', 'save_pitcher',
              'venue_name', 'series_status', 'national_broadcasts',
              'away_probable_pitcher', 'home_probable_pitcher'):
        if sched.get(k) not in (None, ''):
            info[k] = sched[k]

    # Structured seriesStatus for the pregame card's series line. The statsapi
    # schedule wrapper drops this object, so hit the schedule endpoint directly.
    series_status_obj = None
    try:
        raw = statsapi.get('schedule',
                           {'sportId': 1, 'gamePk': game_pk, 'hydrate': 'seriesStatus'})
        series_status_obj = raw['dates'][0]['games'][0].get('seriesStatus')
    except Exception:
        pass

    return {
        'game_info': info,
        'plays': plays,
        'game_data': game,
        'series_status_obj': series_status_obj,
        'linescore_string': statsapi.linescore(game_pk),
        'home_team': statsapi.lookup_team(sched['home_id'])[0],
        'away_team': statsapi.lookup_team(sched['away_id'])[0],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('game_pk', type=int, help='MLB gamePk (game_id)')
    ap.add_argument('out', nargs='?', default=None, help='output JSON path')
    ap.add_argument('--max-plays', type=int, default=None,
                    help='truncate to the first N plays (quicker test)')
    args = ap.parse_args()

    out = args.out or os.path.join(
        os.path.dirname(__file__), '..', 'fixtures', f'game_{args.game_pk}.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)

    fixture = build_fixture(args.game_pk, args.max_plays)
    with open(out, 'w') as f:
        json.dump(fixture, f)

    info = fixture['game_info']
    print("Captured {} plays — {} ({}) @ {} ({})".format(
        len(fixture['plays']),
        info.get('away_name', info['away_id']), info.get('away_score', '?'),
        info.get('home_name', info['home_id']), info.get('home_score', '?')))
    print("Wrote", os.path.relpath(out))


if __name__ == '__main__':
    main()
