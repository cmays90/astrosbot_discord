#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Main entry point for the bot.

This module performs the start-up, login and reads out the settings to configure
the bot.
"""
import logging
import logging.handlers
import json
import sqlite3
import os
import discord
import cards
import BaseballConsumerConstants as constants
from discord.ext import commands
from discord import app_commands

import asyncio
from BaseballConsumerV2 import BaseballUpdaterBotV2, current_pitcher_count
import statsapi
import datetime

DISCORD_SETTINGS_FILE = os.environ.get('DISCORD_SETTINGS_FILE', './discordSettings.doNotUpload.json')
GAME_SETTINGS_FILE = './settings.json'
TEAMS_FILE = './teams.json'

logger = logging.getLogger(__name__)
msgid = 0  # in-flight delay-poll message id, used as a simple concurrency lock

DB_FILE = None
DISCORD_CLIENT_ID = None
DISCORD_CLIENT_SECRET = None
DISCORD_TOKEN = None
DISCORD_GAME_THREAD_CHANNEL_ID = None
DISCORD_GUILD = None
ANNOUNCEMENT_CHANNEL = None
DELETE_ANNOUNCEMENT = False
OWNER_ACCOUNT_ID = None

_LOG_FORMAT = '%(asctime)s %(levelname)s:%(name)s:%(message)s'
_LOG_DIR = 'BaseballConsumer/logs'
os.makedirs(_LOG_DIR, exist_ok=True)

_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(logging.Formatter(_LOG_FORMAT))

_file_handler = logging.handlers.RotatingFileHandler(
    filename=os.path.join(_LOG_DIR, 'bot.log'),
    maxBytes=10 * 1024 * 1024,  # 10 MB per file
    backupCount=99,             # 99 backups + 1 active = 100 files ≈ 1 GB total
    encoding='utf-8',
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))

logging.basicConfig(level=logging.INFO, handlers=[_stream_handler, _file_handler])


def _db_get_thread(game_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute('SELECT thread_id FROM game_threads WHERE game_id = ?', (str(game_id),)).fetchone()
    return row[0] if row else None

def _db_set_thread(game_id: str, thread_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('INSERT OR REPLACE INTO game_threads (game_id, thread_id) VALUES (?, ?)',
                     (str(game_id), str(thread_id)))

def _db_get_all_thread_ids():
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute('SELECT thread_id FROM game_threads').fetchall()
    return {row[0] for row in rows}

def _db_get_game_by_thread(thread_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute('SELECT game_id FROM game_threads WHERE thread_id = ?',
                           (str(thread_id),)).fetchone()
    return row[0] if row else None

def _db_get_event(game_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute('SELECT event_id FROM game_events WHERE game_id = ?', (str(game_id),)).fetchone()
    return row[0] if row else None

def _db_set_event(game_id: str, event_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('INSERT OR REPLACE INTO game_events (game_id, event_id) VALUES (?, ?)',
                     (str(game_id), str(event_id)))

def _db_get_announcement(game_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute('SELECT msg_id FROM game_announcements WHERE game_id = ?', (str(game_id),)).fetchone()
    return row[0] if row else None

def _db_set_announcement(game_id: str, msg_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('INSERT OR REPLACE INTO game_announcements (game_id, msg_id) VALUES (?, ?)',
                     (str(game_id), str(msg_id)))

def _init_tables():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS game_threads (
            game_id   TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS game_events (
            game_id  TEXT PRIMARY KEY,
            event_id TEXT NOT NULL
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS game_announcements (
            game_id TEXT PRIMARY KEY,
            msg_id  TEXT NOT NULL
        )''')

def _migrate_json_to_db():
    with sqlite3.connect(DB_FILE) as conn:
        thread_count = conn.execute('SELECT COUNT(*) FROM game_threads').fetchone()[0]
        if thread_count == 0 and os.path.exists('./threads.json'):
            with open('./threads.json') as f:
                threads = json.load(f)
            for game_id, thread_id in threads.items():
                if game_id != 'game_id':  # skip malformed entry present in legacy file
                    conn.execute('INSERT OR IGNORE INTO game_threads (game_id, thread_id) VALUES (?, ?)',
                                 (str(game_id), str(thread_id)))
            logger.info("Migrated %d threads from threads.json to DB", len(threads))

        event_count = conn.execute('SELECT COUNT(*) FROM game_events').fetchone()[0]
        if event_count == 0 and os.path.exists('./events.json'):
            with open('./events.json') as f:
                events = json.load(f)
            for game_id, event_id in events.items():
                conn.execute('INSERT OR IGNORE INTO game_events (game_id, event_id) VALUES (?, ?)',
                             (str(game_id), str(event_id)))
            logger.info("Migrated %d events from events.json to DB", len(events))


def read_settings():
    global DB_FILE, DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_TOKEN
    global DISCORD_GAME_THREAD_CHANNEL_ID, DISCORD_GUILD, ANNOUNCEMENT_CHANNEL, DELETE_ANNOUNCEMENT
    global OWNER_ACCOUNT_ID

    errors = []

    with open(GAME_SETTINGS_FILE) as f:
        game_settings = json.load(f)
        DB_FILE = game_settings.get('DB_FILE')
        if DB_FILE is None:
            errors.append("Missing DB_FILE")

    with open(DISCORD_SETTINGS_FILE) as f:
        settings = json.load(f)
        DISCORD_CLIENT_ID = settings.get('DISCORD_CLIENT_ID')
        if DISCORD_CLIENT_ID is None:
            errors.append("Missing DISCORD_CLIENT_ID")
        DISCORD_CLIENT_SECRET = settings.get('DISCORD_CLIENT_SECRET')
        if DISCORD_CLIENT_SECRET is None:
            errors.append("Missing DISCORD_CLIENT_SECRET")
        DISCORD_TOKEN = settings.get('DISCORD_TOKEN')
        if DISCORD_TOKEN is None:
            errors.append("Missing DISCORD_TOKEN")
        DISCORD_GAME_THREAD_CHANNEL_ID = settings.get('DISCORD_GAME_THREAD_CHANNEL_ID')
        if DISCORD_GAME_THREAD_CHANNEL_ID is None:
            errors.append("Missing DISCORD_GAME_THREAD_CHANNEL_ID")
        DISCORD_GUILD = settings.get('DISCORD_GUILD')
        if DISCORD_GUILD is None:
            errors.append("Missing DISCORD_GUILD")
        ANNOUNCEMENT_CHANNEL = settings.get('ANNOUNCEMENT_CHANNEL')
        if ANNOUNCEMENT_CHANNEL is None:
            errors.append("Missing ANNOUNCEMENT_CHANNEL")
        DELETE_ANNOUNCEMENT = settings.get('DELETE_ANNOUNCEMENT', False)
        OWNER_ACCOUNT_ID = settings.get('OWNER_ACCOUNT_ID')
        if OWNER_ACCOUNT_ID is None:
            logger.warning("Missing OWNER_ACCOUNT_ID — the !sync command will be disabled.")

    if errors:
        for error in errors:
            print(error)
        exit("Exiting due to missing setting")

    _init_tables()
    _migrate_json_to_db()
    return 0


async def my_background_task(_queue):
    logger.info("setting up background task")
    baseball_updater_bot_v2 = BaseballUpdaterBotV2()
    await asyncio.sleep(2)
    while True:
        logger.info("Running background task")
        try:
            await baseball_updater_bot_v2.run(_queue)
        except Exception:
            logger.exception("Unknown error in baseball tasks.")
        await asyncio.sleep(3)


async def _close_thread_after_delay(thread, delay_seconds=1800):
    """Wait delay_seconds then archive and lock the game thread."""
    await asyncio.sleep(delay_seconds)
    try:
        await thread.edit(archived=True, locked=True)
        logger.info("Thread %s closed and locked after %ds delay", thread.id, delay_seconds)
    except Exception:
        logger.exception("Failed to close/lock thread %s", thread.id)


async def discord_poster(bot, _queue):
    try:
        await bot.wait_until_ready()
        logger.info("discord poster is running")
    except Exception:
        logger.exception("Fatal error in discord_poster setup", exc_info=True)

    while True:
        try:
            item = await _queue.get()
            thread = None

            if "game_id" in item and item["game_id"] is not None:
                thread_id = _db_get_thread(str(item['game_id']))
                if thread_id is not None:
                    logger.info(f"game_id: {item['game_id']}")
                    thread = bot.get_channel(int(thread_id))
                    if thread is None:
                        guild = bot.get_guild(int(DISCORD_GUILD))
                        active_threads = await guild.active_threads()
                        for t in active_threads:
                            if t.id == int(thread_id):
                                thread = t
                                break
                else:
                    with open(TEAMS_FILE) as f:
                        teams = json.load(f)

                    schedule = await asyncio.to_thread(statsapi.schedule, game_id=item['game_id'])
                    game = schedule[0]
                    start_time = datetime.datetime.strptime(game['game_datetime'], "%Y-%m-%dT%H:%M:%S%z")
                    summary = (
                        f"<t:{int(start_time.timestamp())}:t> | "
                        f"{teams[str(game['away_id'])]['flair']} @ {teams[str(game['home_id'])]['flair']}"
                        f"{ ' | Game ' + str(game['game_num']) if game['doubleheader'] != 'N' else '' }"
                    )
                    channel = bot.get_channel(int(DISCORD_GAME_THREAD_CHANNEL_ID))
                    msg = await channel.send(summary)
                    thread = await msg.create_thread(
                        name=(
                            f"⚾ | {teams[str(game['away_id'])]['short']} at {teams[str(game['home_id'])]['short']}"
                            f"{ ' | Game ' + str(game['game_num']) if game['doubleheader'] != 'N' else '' }"
                            f" | {game['game_date']}"
                        )
                    )
                    _db_set_thread(str(item['game_id']), str(thread.id))
                    logger.info(f"New thread: {thread.id}")

                    guild = bot.get_guild(int(DISCORD_GUILD))
                    event = await guild.create_scheduled_event(
                        name=(
                            f"{teams[str(game['away_id'])]['short']} @ {teams[str(game['home_id'])]['short']}"
                            f"{' | Game ' + str(game['game_num']) if game['doubleheader'] != 'N' else ''}"
                        ),
                        start_time=start_time,
                        end_time=start_time + datetime.timedelta(days=1),
                        entity_type=discord.EntityType.external,
                        privacy_level=discord.PrivacyLevel.guild_only,
                        location=f"https://discord.com/channels/{DISCORD_GUILD}/{thread.id}"
                    )
                    _db_set_event(str(item['game_id']), str(event.id))

                    announcement_channel = bot.get_channel(int(ANNOUNCEMENT_CHANNEL))
                    a_msg = await announcement_channel.send(f"https://discord.gg/astros?event={event.id}")
                    await a_msg.publish()
                    _db_set_announcement(str(item['game_id']), str(a_msg.id))

            if "active_game" in item and item["active_game"]:
                await asyncio.sleep(constants.DELAY)

            if thread is not None:
                if item.get('view') is not None:
                    if item.get('bases_image'):
                        await thread.send(
                            view=item['view'],
                            files=[discord.File(item['bases_image'], filename=cards.BASES_ATTACHMENT)])
                    else:
                        await thread.send(view=item['view'])
                elif item.get('embed') and (item['embed'].title or item['embed'].description):
                    await thread.send(embed=item['embed'])
                if item.get('msg'):
                    await thread.send(item['msg'])
            elif item.get('view') is not None or 'embed' in item or 'msg' in item:
                logger.info("Thread is none! Should not be none!")

            if 'extras' in item and 'event_end' in item['extras'] and item['extras']['event_end']:
                # Complete the Discord scheduled event
                try:
                    event_id = _db_get_event(str(item['game_id']))
                    if event_id is not None:
                        guild = bot.get_guild(int(DISCORD_GUILD))
                        event = await guild.fetch_scheduled_event(int(event_id))
                        await event.edit(status=discord.EventStatus.completed)
                    else:
                        logger.warning("No Discord event found for game_id %s; skipping event_end", item['game_id'])
                except Exception:
                    logger.exception("Failed to complete Discord event (event_id=%s, game_id=%s)", event_id, item['game_id'])

                # Delete the announcement channel post (if enabled)
                if DELETE_ANNOUNCEMENT:
                    ann_msg_id = _db_get_announcement(str(item['game_id']))
                    if ann_msg_id is not None:
                        try:
                            announcement_channel = bot.get_channel(int(ANNOUNCEMENT_CHANNEL))
                            ann_msg = await announcement_channel.fetch_message(int(ann_msg_id))
                            await ann_msg.delete()
                            logger.info("Deleted announcement message %s for game_id %s", ann_msg_id, item['game_id'])
                        except Exception:
                            logger.exception("Failed to delete announcement message %s", ann_msg_id)
                    else:
                        logger.warning("No announcement message found for game_id %s; skipping delete", item['game_id'])

                # Close and lock the game thread 30 minutes after the game ends
                if thread is not None:
                    asyncio.create_task(_close_thread_after_delay(thread, delay_seconds=1800))
                    logger.info("Scheduled thread %s to close in 30 minutes", thread.id)
                else:
                    logger.warning("Thread is None at event_end for game_id %s; cannot schedule close", item['game_id'])

            if 'extras' in item and 'event_start' in item['extras'] and item['extras']['event_start']:
                try:
                    event_id = _db_get_event(str(item['game_id']))
                    if event_id is not None:
                        guild = bot.get_guild(int(DISCORD_GUILD))
                        event = await guild.fetch_scheduled_event(int(event_id))
                        await event.edit(status=discord.EventStatus.active)
                    else:
                        logger.warning("No Discord event found for game_id %s; skipping event_start", item['game_id'])
                except Exception:
                    logger.exception("Failed to start Discord event (event_id=%s, game_id=%s)", event_id, item['game_id'])

        except Exception:
            logger.exception("Fatal error in discord_poster loop", exc_info=True)


class BaseballCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def delay(self, ctx, _delay: int = -1):
        """Adds a delay to events during a game."""
        if str(ctx.channel.id) not in _db_get_all_thread_ids() and str(ctx.channel.id) != '819386486742319104':
            await ctx.reply("This command is not available in this channel.")
            return
        global msgid
        if _delay < 0:
            await ctx.reply(f"The current delay is {constants.DELAY}")
            return
        if _delay > 120:
            _delay = 120
        if msgid != 0:
            await ctx.reply("I am already running a poll!")
            return
        try:
            # Discord's minimum poll duration is 1 hour, so we open it and end it
            # early to keep the original 30-second voting window.
            poll = discord.Poll(
                question=f"Set a {_delay} second delay before events post to this channel?",
                duration=datetime.timedelta(hours=1),
            )
            poll.add_answer(text="Yes", emoji="✅")
            poll.add_answer(text="No", emoji="❌")
            msg = await ctx.send("30 seconds remaining to vote", poll=poll)
            msgid = msg.id
            for i in range(0, 6):
                await msg.edit(content=f"{30 - i * 5} seconds remaining to vote")
                await asyncio.sleep(5)
            await msg.edit(content="Voting ended.")
            try:
                await msg.end_poll()
            except Exception:
                logger.exception("Failed to end delay poll early")
            # Re-fetch so the final tallies are populated.
            fresh = await ctx.channel.fetch_message(msg.id)
            tally = {a.text: a.vote_count for a in fresh.poll.answers} if fresh.poll else {}
            if tally.get("Yes", 0) > tally.get("No", 0):
                await ctx.send(f"The vote passes!  Delay has been set to {_delay} seconds")
                constants.DELAY = _delay
            else:
                await ctx.send(f"The vote failed!  Delay shall remain {constants.DELAY} seconds")
            msgid = 0
        except Exception:
            msgid = 0
            await ctx.reply("Error running the delay poll")
            raise

    @commands.hybrid_command(name='pitchcount', aliases=['pc'],
                             description="Show both active pitchers' pitch counts.")
    async def pitchcount(self, ctx):
        """Posts the pitch count for both teams' current pitchers."""
        game_id = _db_get_game_by_thread(str(ctx.channel.id))
        if game_id is None:
            await ctx.reply("This command is only available in a game thread.")
            return
        game = await asyncio.to_thread(statsapi.get, 'game', {'gamePk': game_id})
        boxscore = game.get('liveData', {}).get('boxscore', {})
        entries = []
        for side in ('away', 'home'):
            count = current_pitcher_count(boxscore, side)
            if not count:
                continue
            abbv = boxscore.get('teams', {}).get(side, {}).get('team', {}).get('abbreviation', '')
            name, balls, strikes, total = count
            entries.append((abbv or side.title(), name, balls, strikes, total))
        if not entries:
            await ctx.reply("No active pitchers right now.")
            return
        await ctx.reply(view=cards.pitchcount_card(entries))

    @app_commands.command(name='lineups',
                          description="Post both teams' starting lineups.")
    async def lineups(self, interaction: discord.Interaction):
        """Slash-only (no ! prefix) so it doesn't collide with another bot's
        !lineups. Posts both teams' starting lineups for this game thread."""
        game_id = _db_get_game_by_thread(str(interaction.channel.id))
        if game_id is None:
            await interaction.response.send_message(
                "This command is only available in a game thread.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        game = await asyncio.to_thread(statsapi.get, 'game', {'gamePk': game_id})
        view = cards.lineup_card(game)
        if view is None:
            await interaction.followup.send("Lineups aren't available yet.")
            return
        await interaction.followup.send(view=view)

    @commands.command()
    async def sync(self, ctx, guild_id: int = None):
        """Owner-only: (re)sync slash commands globally, or to one guild if given."""
        if OWNER_ACCOUNT_ID is None or str(ctx.author.id) != str(OWNER_ACCOUNT_ID):
            return
        try:
            if guild_id:
                guild = discord.Object(id=guild_id)
                self.bot.tree.copy_global_to(guild=guild)
                synced = await self.bot.tree.sync(guild=guild)
                where = f" to guild {guild_id}"
            else:
                synced = await self.bot.tree.sync()
                where = ""
            await ctx.reply(f"Synced {len(synced)} command(s){where}.")
        except Exception:
            logger.exception('Failed to sync slash commands')
            await ctx.reply("Failed to sync slash commands — check the logs.")

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info('Logged in as %s ||| %s', self.bot.user.name, self.bot.user.id)


class AstrosBot(commands.Bot):
    async def setup_hook(self):
        """Runs once per process, before connecting to the gateway. Sync the
        slash command tree here (not in on_ready, which can fire repeatedly).

        Sync to DISCORD_GUILD specifically: guild syncs apply instantly, while a
        global sync can take up to an hour to propagate (which is why new
        commands weren't showing up on the main server). A guild command
        overrides a same-named global command in that guild, so this does not
        create duplicates."""
        try:
            if DISCORD_GUILD:
                guild = discord.Object(id=int(DISCORD_GUILD))
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info('Synced %d slash command(s) to guild %s', len(synced), DISCORD_GUILD)
            else:
                synced = await self.tree.sync()
                logger.info('Synced %d slash command(s) globally', len(synced))
        except Exception:
            logger.exception('Failed to sync slash commands')


async def main():
    asyncio.get_event_loop().slow_callback_duration = 1
    intents = discord.Intents.default()
    intents.message_content = True
    intents.typing = False
    bot = AstrosBot(command_prefix='!', description="/r/Astros Discord Poster", intents=intents)
    await bot.add_cog(BaseballCog(bot))

    read_settings()

    queue = asyncio.Queue()

    tasks = []
    tasks.append(asyncio.create_task(bot.start(DISCORD_TOKEN)))
    tasks.append(asyncio.create_task(discord_poster(bot, queue)))
    tasks.append(asyncio.create_task(my_background_task(queue)))
    logger.info("loops added")

    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == '__main__':
    asyncio.run(main(), debug=True)
