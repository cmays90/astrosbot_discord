"""
Record a completed MLB game from the live API into a JSON fixture.

Usage:
    python tests/fixtures/record_game.py --game-pk 746011
    python tests/fixtures/record_game.py --game-pk 746011 --out tests/fixtures/game_746011.json

The fixture can then be replayed at high speed:
    replayer = GameReplayer(fixture_path='tests/fixtures/game_746011.json')
"""
import argparse
import json
import os
import sys

# Make statsapi importable from the project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'BaseballConsumer'))

import statsapi  # noqa: E402


def record(game_pk: int, out_path: str):
    print(f"Fetching game {game_pk} …")

    # Schedule item (gives us game_date, team ids, datetime, etc.)
    game_data = statsapi.get('game', {'gamePk': game_pk})
    game_meta = game_data.get('gameData', {})
    teams = game_meta.get('teams', {})
    home_id = teams.get('home', {}).get('id')
    away_id = teams.get('away', {}).get('id')
    game_date = game_meta.get('datetime', {}).get('officialDate', '')
    game_datetime = game_meta.get('datetime', {}).get('dateTime', '')
    status = game_meta.get('status', {}).get('detailedState', 'Final')

    print(f"  Home: {home_id}  Away: {away_id}  Status: {status}")

    # All plays (complete game)
    all_plays = game_data['liveData']['plays']['allPlays']
    linescore_data = game_data['liveData']['linescore']
    boxscore_data = game_data['liveData'].get('boxscore', {})
    print(f"  Total plays: {len(all_plays)}")

    # Formatted linescore string
    linescore_string = statsapi.linescore(game_pk)

    # Team info
    home_team_list = statsapi.lookup_team(home_id)
    away_team_list = statsapi.lookup_team(away_id)
    home_team = home_team_list[0] if home_team_list else {}
    away_team = away_team_list[0] if away_team_list else {}

    # Schedule item (for discord_poster thread-creation path)
    schedule = statsapi.schedule(game_id=game_pk)
    game_sched = schedule[0] if schedule else {}

    fixture = {
        'game_info': {
            'game_id': game_pk,
            'game_date': game_date,
            'game_datetime': game_datetime,
            'home_id': home_id,
            'away_id': away_id,
            'game_num': game_sched.get('game_num', 1),
            'doubleheader': game_sched.get('doubleheader', 'N'),
            'status': status,
        },
        'plays': all_plays,
        'game_data': {
            'liveData': {
                'plays': {'allPlays': all_plays},
                'linescore': linescore_data,
                'boxscore': boxscore_data,
            }
        },
        'linescore_string': linescore_string,
        'home_team': home_team,
        'away_team': away_team,
    }

    with open(out_path, 'w') as f:
        json.dump(fixture, f, indent=2)

    size_kb = os.path.getsize(out_path) // 1024
    print(f"Saved to {out_path} ({size_kb} KB, {len(all_plays)} plays)")


def main():
    parser = argparse.ArgumentParser(description="Record an MLB game fixture for replay testing.")
    parser.add_argument('--game-pk', type=int, required=True, help="MLB gamePk (e.g. 746011)")
    parser.add_argument(
        '--out', type=str, default=None,
        help="Output JSON path (default: tests/fixtures/game_<pk>.json)"
    )
    args = parser.parse_args()

    out = args.out or os.path.join(
        os.path.dirname(__file__), f'game_{args.game_pk}.json'
    )
    record(args.game_pk, out)


if __name__ == '__main__':
    main()
