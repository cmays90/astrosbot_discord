"""
Scenario: replay a full game from Scheduled through Final.

Run:
    pytest tests/scenarios/full_game.py -v
    pytest tests/scenarios/full_game.py -v -s   # print captured events

Real Discord (test server):
    DISCORD_SETTINGS_FILE=discordSettings.test.doNotUpload.json \
        USE_REAL_DISCORD=true pytest tests/scenarios/full_game.py -v -s

Real MLB + mock Discord:
    USE_REAL_MLB=true MLB_GAME_PK=746011 pytest tests/scenarios/full_game.py -v -s
"""
import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'BaseballConsumer'))

from mocks.mlb_mock import GameReplayer, build_minimal_fixture
from mocks.discord_mock import MockBot
from harness import Harness, RealDiscordBackend


def _make_mlb():
    if os.environ.get('USE_REAL_MLB', '').lower() == 'true':
        # Real MLB API — wrap it so the harness sees game_over at Final.
        import statsapi as _real_statsapi
        game_pk = int(os.environ.get('MLB_GAME_PK', '0'))
        if not game_pk:
            pytest.skip("Set MLB_GAME_PK env var to use real MLB")
        from fixtures.record_game import record
        import tempfile, json
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tmp = f.name
        record(game_pk, tmp)
        with open(tmp) as f:
            data = json.load(f)
        os.unlink(tmp)
        return GameReplayer(fixture_data=data, plays_per_poll=3)
    else:
        return GameReplayer(fixture_data=build_minimal_fixture(num_plays=15), plays_per_poll=3)


def _make_discord():
    if os.environ.get('USE_REAL_DISCORD', '').lower() == 'true':
        settings = os.environ.get(
            'DISCORD_SETTINGS_FILE', 'discordSettings.test.doNotUpload.json'
        )
        return RealDiscordBackend(settings)
    return MockBot()


@pytest.mark.asyncio
async def test_full_game():
    mlb = _make_mlb()
    disc = _make_discord()
    speed = 1 if os.environ.get('USE_REAL_DISCORD', '').lower() == 'true' else 1000

    harness = Harness(mlb, disc, speed_factor=speed)
    try:
        await harness.run(timeout=60)
    finally:
        harness.cleanup()

    if isinstance(disc, MockBot):
        print("\n=== Event log summary ===")
        print(disc.summary())

        # A thread must have been created for the game.
        threads = disc.threads_created()
        assert threads, "Expected a game thread to be created"

        # At least one play-by-play message must have been posted.
        thread_msgs = disc.messages_to_threads()
        assert thread_msgs, "Expected play-by-play messages in the game thread"

        # Game-started embed should have been sent.
        embed_msgs = [e for e in disc.event_log if e.get('has_embed')]
        assert embed_msgs, "Expected at least one embed message"

        # The Discord scheduled event must have been created and then completed.
        events_created = disc.events_created()
        assert events_created, "Expected a Discord scheduled event to be created"

        completed = [
            e for e in disc.event_log
            if e['type'] == 'event_status_changed' and 'completed' in str(e.get('status', '')).lower()
        ]
        assert completed, "Expected the scheduled event to be marked completed"

        print(f"  Threads created:  {len(threads)}")
        print(f"  Thread messages:  {len(thread_msgs)}")
        print(f"  Events created:   {len(events_created)}")
        print(f"  Event completed:  {len(completed)}")
