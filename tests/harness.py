"""
Test harness — wires MLB and Discord backends together and drives the bot
through a complete game at high speed.

Usage (mock everything, 1000× faster than real time):

    from tests.mocks.mlb_mock import GameReplayer, build_minimal_fixture
    from tests.mocks.discord_mock import MockBot
    from tests.harness import Harness

    mlb  = GameReplayer(fixture_data=build_minimal_fixture())
    disc = MockBot()
    result = asyncio.run(Harness(mlb, disc).run())
    disc.dump()

Usage (mock MLB, post to a real test Discord server):

    from tests.harness import RealDiscordBackend
    disc = RealDiscordBackend('discordSettings.test.doNotUpload.json')
    result = asyncio.run(Harness(mlb, disc).run(timeout=120))
"""
import asyncio
import logging
import os
import sys
import tempfile

# Ensure bot modules are importable without a package prefix.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'BaseballConsumer'))

logger = logging.getLogger(__name__)

# Absolute path to teams.json at project root.
_TEAMS_FILE = os.path.join(os.path.dirname(__file__), '..', 'teams.json')


class Harness:
    """
    Orchestrates a full bot run for testing.

    Parameters
    ----------
    mlb:
        A GameReplayer (mock) or a real statsapi-compatible object.
    discord:
        A MockBot (mock) or a RealDiscordBackend (real server).
    speed_factor:
        Divides every asyncio.sleep() duration.  1000 = 1 000× faster.
        Set to 1 for real-time runs (e.g. integration against a live game).
    db_file:
        Path to the SQLite DB.  Defaults to a fresh temp file per run.
    """

    def __init__(self, mlb, discord, speed_factor: float = 1000, db_file: str = None):
        self.mlb = mlb
        self.discord = discord
        self.speed_factor = speed_factor
        self._db_file = db_file
        self._temp_db: str = None

    async def run(self, timeout: float = 60) -> "MockBot | RealDiscordBackend":
        """
        Run the bot until the game ends, then return the discord backend.

        Raises asyncio.TimeoutError if the game doesn't finish within
        `timeout` real seconds.
        """
        import MainEntryBot as meb
        import BaseballConsumerV2  # noqa: F401 — ensures module is in sys.modules

        # ------------------------------------------------------------------ #
        #  Database                                                            #
        # ------------------------------------------------------------------ #
        if self._db_file:
            db_path = self._db_file
        else:
            fd, db_path = tempfile.mkstemp(suffix='.db', prefix='astros_test_')
            os.close(fd)
            self._temp_db = db_path

        # ------------------------------------------------------------------ #
        #  Configure MainEntryBot module-level globals                        #
        # ------------------------------------------------------------------ #
        meb.DB_FILE = db_path
        meb.DISCORD_GUILD = self.discord.guild_id
        meb.DISCORD_GAME_THREAD_CHANNEL_ID = self.discord.game_thread_channel_id
        meb.ANNOUNCEMENT_CHANNEL = self.discord.announcement_channel_id
        meb.DELETE_ANNOUNCEMENT = False
        meb.TEAMS_FILE = _TEAMS_FILE
        meb._init_tables()

        # ------------------------------------------------------------------ #
        #  Redirect BaseballConsumerV2's own DB (posted_events table) to the  #
        #  same temp DB.  The module reads its DB path from settings.json via  #
        #  BaseballUpdaterBotV2.read_settings(); we override the settings file #
        #  path at the module level so the poller uses the fresh test DB.      #
        # ------------------------------------------------------------------ #
        import json as _json
        import BaseballConsumerV2 as _bcv2
        fd2, _test_settings_path = tempfile.mkstemp(suffix='.json', prefix='astros_settings_')
        os.close(fd2)
        with open(_test_settings_path, 'w') as _f:
            _json.dump({'DB_FILE': db_path, 'TEAM_ID': 117}, _f)
        _orig_settings_file = _bcv2.SETTINGS_FILE
        _bcv2.SETTINGS_FILE = _test_settings_path

        # ------------------------------------------------------------------ #
        #  Choose the bot object                                               #
        # ------------------------------------------------------------------ #
        bot = getattr(self.discord, 'bot', self.discord)

        # ------------------------------------------------------------------ #
        #  Patch asyncio.sleep for speed                                       #
        # ------------------------------------------------------------------ #
        _original_sleep = asyncio.sleep
        _sf = self.speed_factor

        async def _fast_sleep(seconds, *args, **kwargs):
            await _original_sleep(max(0.001, seconds / _sf))

        # Patch at the module level so all `await asyncio.sleep(...)` calls
        # inside the bot modules go through the accelerated version.
        import asyncio as _asyncio_mod
        _asyncio_mod.sleep = _fast_sleep

        # ------------------------------------------------------------------ #
        #  Patch statsapi                                                      #
        # ------------------------------------------------------------------ #
        import sys as _sys
        _originals = {}
        for mod_name in ('BaseballConsumerV2', 'MainEntryBot'):
            mod = _sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, 'statsapi'):
                _originals[mod_name] = (mod, mod.statsapi)
                mod.statsapi = self.mlb

        try:
            # Do NOT use asyncio.wait_for here — it calls asyncio.sleep
            # internally, which we've patched, so the timeout would be
            # compressed by speed_factor.  The monitor task handles wall-clock
            # timeout via time.monotonic() instead.
            await self._run_tasks(meb, bot, db_path, _original_sleep, timeout)
        finally:
            # Restore asyncio.sleep, statsapi, and settings file path.
            _asyncio_mod.sleep = _original_sleep
            for _name, (mod, orig) in _originals.items():
                mod.statsapi = orig
            _bcv2.SETTINGS_FILE = _orig_settings_file
            try:
                os.unlink(_test_settings_path)
            except OSError:
                pass

        return self.discord

    async def _run_tasks(self, meb, bot, db_path, real_sleep, timeout):
        import time
        mlb = self.mlb
        queue = asyncio.Queue()

        tasks_to_cancel = []

        # Start the real Discord bot connection if needed.
        if isinstance(self.discord, RealDiscordBackend):
            bot_task = asyncio.create_task(self.discord.start())
            tasks_to_cancel.append(bot_task)
            # Give the bot time to connect before posting begins.
            await real_sleep(3)

        poster_task = asyncio.create_task(meb.discord_poster(bot, queue))
        bg_task = asyncio.create_task(meb.my_background_task(queue))
        tasks_to_cancel += [poster_task, bg_task]

        deadline = time.monotonic() + timeout  # wall-clock, unaffected by sleep patch

        async def _monitor():
            while True:
                await real_sleep(0.05)
                if mlb.game_over and queue.empty():
                    # Small extra wait so discord_poster can finish processing
                    # the final status message before we cancel.
                    await real_sleep(0.5)
                    for t in tasks_to_cancel:
                        t.cancel()
                    return
                if time.monotonic() > deadline:
                    logger.warning("Harness timed out after %.0fs real time", timeout)
                    for t in tasks_to_cancel:
                        t.cancel()
                    return

        monitor_task = asyncio.create_task(_monitor())

        results = await asyncio.gather(
            poster_task, bg_task, monitor_task, return_exceptions=True
        )
        # CancelledError is expected for poster_task and bg_task; log
        # anything unexpected.
        for r in results:
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
                logger.warning("Task raised: %s", r)

    def cleanup(self):
        """Delete the temp DB created for this run."""
        if self._temp_db and os.path.exists(self._temp_db):
            os.unlink(self._temp_db)


# --------------------------------------------------------------------------- #
#  Real Discord backend                                                        #
# --------------------------------------------------------------------------- #

class RealDiscordBackend:
    """
    Backend that connects to a real Discord test server.

    The settings file has the same schema as discordSettings.doNotUpload.json
    but points at a dedicated test guild/channels.  Keep it out of git.

    Typical filename: discordSettings.test.doNotUpload.json
    """

    def __init__(self, settings_file: str = 'discordSettings.test.doNotUpload.json'):
        import json
        import discord
        from discord.ext import commands

        settings_path = settings_file if os.path.isabs(settings_file) else \
            os.path.join(os.path.dirname(__file__), '..', settings_file)

        with open(settings_path) as f:
            cfg = json.load(f)

        missing = [k for k in (
            'DISCORD_TOKEN', 'DISCORD_GUILD',
            'DISCORD_GAME_THREAD_CHANNEL_ID', 'ANNOUNCEMENT_CHANNEL'
        ) if k not in cfg]
        if missing:
            raise ValueError(f"Missing keys in {settings_file}: {missing}")

        self.guild_id = str(cfg['DISCORD_GUILD'])
        self.game_thread_channel_id = str(cfg['DISCORD_GAME_THREAD_CHANNEL_ID'])
        self.announcement_channel_id = str(cfg['ANNOUNCEMENT_CHANNEL'])
        self.token = cfg['DISCORD_TOKEN']

        intents = discord.Intents.default()
        intents.message_content = True
        intents.typing = False
        self.bot = commands.Bot(command_prefix='!', intents=intents)

    async def start(self):
        """Start the real Discord bot.  Called automatically by Harness."""
        await self.bot.start(self.token)
