'''

BASEBALL GAME THREAD BOT

Written by:
KimbaWLion

Please contact us on Github if you have any questions.

'''
import sqlite3
import requests
import statsapi
from requests.exceptions import HTTPError

# MLB Stats API fingerprints the TLS handshake on some VPS IPs and returns 406
# for python-requests (OpenSSL JA3). curl_cffi uses libcurl's TLS stack so the
# handshake looks like a real browser. Monkey-patch requests.get so every
# statsapi call goes through curl_cffi without changing any other code.
try:
    import curl_cffi.requests as _cffi_requests
    def _patched_requests_get(url, **kwargs):
        kwargs.pop('headers', None)  # curl_cffi sets its own headers
        return _cffi_requests.get(url, impersonate='chrome', **kwargs)
    requests.get = _patched_requests_get
    import logging as _log; _log.getLogger(__name__).info("curl_cffi patch active")
except ImportError:
    import logging as _log; _log.getLogger(__name__).warning(
        "curl_cffi not installed — falling back to plain requests (may get 406 on VPS)"
    )
from datetime import datetime, timedelta
import asyncio
import discord
import json
import BaseballConsumerConstants as constants
import logging
import pytz

SETTINGS_FILE = './settings.json'

logger = logging.getLogger(__name__)


def format_pitch_count_line(name, balls, strikes, total):
    return "{} — Balls: {}, Strikes: {}, Total: {}".format(name, balls, strikes, total)


def current_pitcher_count(boxscore, side):
    """side in {'home','away'}. Returns (name, balls, strikes, total) or None."""
    team = boxscore.get('teams', {}).get(side, {})
    pitchers = team.get('pitchers') or []
    if not pitchers:
        return None
    pid = pitchers[-1]
    player = team.get('players', {}).get('ID{}'.format(pid))
    if not player:
        return None
    pit = player.get('stats', {}).get('pitching', {})
    if not pit:
        return None
    return (player['person']['fullName'],
            pit.get('balls', 0), pit.get('strikes', 0),
            pit.get('pitchesThrown', pit.get('numberOfPitches', 0)))


class BaseballUpdaterBotV2:

    async def run(self, queue):
        await asyncio.sleep(1)
        logger.info("In baseball run")
        try:
            time = datetime.now()
            error_msg = self.read_settings()
            if error_msg != 0:
                logger.info(error_msg)
                return

            logger.info('in BaseballUpdaterBotV2.run()')
            self._init_db()
            current_game_date = None
            ids_of_prev_events = set()

            while True:
                await asyncio.sleep(1)
                todays_game = (datetime.now(tz=pytz.timezone('US/Central')) - timedelta(hours=5))
                game_date_str = todays_game.strftime("%Y-%m-%d")
                if game_date_str != current_game_date:
                    current_game_date = game_date_str
                    ids_of_prev_events = self._load_todays_events(game_date_str)

                t = datetime.now(tz=pytz.timezone('US/Central'))
                future = datetime(t.year, t.month, t.day, 5, 0, tzinfo=pytz.timezone('US/Central'))
                if t.hour >= 5:
                    future += timedelta(days=1)
                how_long_to_wait_in_sec = (future-t).total_seconds()

                await asyncio.sleep(0.2)

                retry = 0
                while True:
                    try:
                        schedule = await asyncio.to_thread(
                            statsapi.schedule, date=todays_game.strftime("%Y-%m-%d"), team=self.TEAM_ID
                        )
                        break
                    except HTTPError as e:
                        logger.warning("HTTPError fetching schedule (HTTP %s): %s",
                                       e.response.status_code if e.response is not None else '?',
                                       e.response.text[:500] if e.response is not None else str(e))
                        await asyncio.sleep(2*retry+1)
                        if retry < 30:
                            retry += 1

                if not schedule:
                    no_game_id = ''.join(["NoGameToday", todays_game.strftime("%Y-%m-%d")])
                    if no_game_id not in ids_of_prev_events:
                        await self.postNoGameStatusOnDiscord(queue)
                        self._log_event(no_game_id, game_date_str, "No Game Today")
                        ids_of_prev_events.add(no_game_id)

                    logger.info(f"Sleeping {how_long_to_wait_in_sec} seconds (no game)")
                for game in schedule:
                    home_team_names = await self.lookupTeamInfo(game['home_id'])
                    away_team_names = await self.lookupTeamInfo(game['away_id'])

                    # First, check if the game status has changed
                    game_status = game['status']
                    gameStatusId = ''.join([game_status.replace(" ", ""), ';', str(game['game_id'])])
                    if gameStatusId not in ids_of_prev_events:
                        await self.postGameStatusOnDiscord(queue, game)
                        self._log_event(gameStatusId, game_date_str, game_status)
                        ids_of_prev_events.add(gameStatusId)

                    logger.info("Game is %s.", game_status)

                    # Change the update period based on the game_status
                    if game_status in ['Scheduled']:
                        if how_long_to_wait_in_sec > 300:
                            how_long_to_wait_in_sec = 300
                    elif game_status in ['Pre-Game', 'Warmup', 'Game Over'] \
                            or 'Delay' in game_status \
                            or 'Suspended' in game_status:
                        if how_long_to_wait_in_sec > 60:
                            how_long_to_wait_in_sec = 60
                    elif game_status in ['Final', 'Completed Early: Rain', 'Game Over: Tied', 'Final: Tied', 'Game Over']:
                        constants.DELAY = constants.DEFAULT_DELAY
                    elif game_status == 'In Progress':
                        how_long_to_wait_in_sec = 10

                        # Game Event logic
                        retry = 0
                        while True:
                            try:
                                game_info = await asyncio.to_thread(
                                    statsapi.get, 'game', {'gamePk': game['game_id']}
                                )
                                break
                            except HTTPError as e:
                                logger.warning("HTTPError fetching game (HTTP %s): %s",
                                               e.response.status_code if e.response is not None else '?',
                                               e.response.text[:500] if e.response is not None else str(e))
                                await asyncio.sleep(2 * retry + 1)
                                if retry < 30:
                                    retry += 1
                        live_data = game_info['liveData']
                        plays = live_data['plays']['allPlays']
                        linescore = live_data['linescore']
                        boxscore = live_data.get('boxscore', {})
                        retry = 0
                        while True:
                            try:
                                fullLinescoreString = await asyncio.to_thread(
                                    statsapi.linescore, game['game_id']
                                )
                                break
                            except HTTPError as e:
                                logger.warning("HTTPError fetching linescore (HTTP %s): %s",
                                               e.response.status_code if e.response is not None else '?',
                                               e.response.text[:500] if e.response is not None else str(e))
                                await asyncio.sleep(2 * retry + 1)
                                if retry < 30:
                                    retry += 1

                        strikeout_tracker = {'home': [], 'away': []}  # Boolean list, true = swinging, false = looking
                        for play in plays:
                            # If the item is not full yet (as in the atbat is finished) skip
                            if not 'description' in play['result'].keys():
                                continue

                            # Get info from plays
                            info = {}
                            info['homeTeamFullName'] = home_team_names['name']
                            info['homeTeamName'] = home_team_names['teamName']
                            info['homeTeamShortFullName'] = home_team_names['shortName']
                            info['homeTeamAbbv'] = home_team_names['fileCode']
                            info['awayTeamFullName'] = away_team_names['name']
                            info['awayTeamName'] = away_team_names['teamName']
                            info['awayTeamShortFullName'] = away_team_names['shortName']
                            info['awayTeamAbbv'] = away_team_names['fileCode']
                            info['startTime'] = play['about']['startTime']
                            info['inning'] = str(play['about']['inning'])
                            info['inningHalf'] = play['about']['halfInning']
                            info['atBatIndex'] = str(play['about']['atBatIndex'])
                            info['balls'] = str(play['count']['balls'])
                            info['strikes'] = str(play['count']['strikes'])
                            info['outs'] = str(play['count']['outs'])
                            info['homeScore'] = str(play['result']['homeScore'])
                            info['awayScore'] = str(play['result']['awayScore'])
                            info['description'] = play['result']['description']
                            info['event'] = play['result']['event']
                            info['rbi'] = play['result']['rbi']
                            info['playType'] = play['result']['type']
                            info['manOnFirst'] = True if 'postOnFirst' in play['matchup'] else False
                            info['manOnSecond'] = True if 'postOnSecond' in play['matchup'] else False
                            info['manOnThird'] = True if 'postOnThird' in play['matchup'] else False
                            info['runsScored'] = 0
                            info['rbis'] = 0
                            info['runsEarned'] = 0
                            for runner in play['runners']:
                                info['runsScored'] += 1 if runner['details']['isScoringEvent'] else 0
                                info['rbis'] += 1 if runner['details']['rbi'] else 0
                                info['runsEarned'] += 1 if runner['details']['earned'] else 0

                            # Get info from linescore
                            info['outs_linescore'] = linescore['outs']
                            info['homeStats_linescore'] = linescore['teams']['home']  # runs, hits, errors, lefOnBase
                            info['awayStats_linescore'] = linescore['teams']['away']
                            info['currentInning_linescore'] = linescore['currentInning']
                            info['inningState_linescore'] = linescore['inningState']  # Middle or End
                            info['inningHalf_linescore'] = linescore['inningHalf']

                            # Get full linescore summary
                            info['fullLinescoreString'] = fullLinescoreString

                            # Pitch count for the pitcher currently pitching (the
                            # fielding side of this half-inning). Frozen here so the
                            # end-of-inning message reflects state at processing time.
                            pitching_side = 'away' if self.homeTeamBatting(info) else 'home'
                            info['pitcherCount'] = current_pitcher_count(boxscore, pitching_side)

                            # playType isn't working, do it yourself
                            info['playTypeActual'] = self.getPlayType(info['description'])

                            # Update strikeout tracker
                            if info['event'] == 'Strikeout':
                                if self.homeTeamBatting(info):
                                    currentStrikeouts = strikeout_tracker['away']
                                    if "strikes out" in info['description']:
                                        currentStrikeouts.append(True)
                                    if "called out on strikes" in info['description']:
                                        currentStrikeouts.append(False)
                                    strikeout_tracker['away'] = currentStrikeouts
                                else:
                                    currentStrikeouts = strikeout_tracker['home']
                                    if "strikes out" in info['description']:
                                        currentStrikeouts.append(True)
                                    if "called out on strikes" in info['description']:
                                        currentStrikeouts.append(False)
                                    strikeout_tracker['home'] = currentStrikeouts
                            info['strikeoutTracker'] = strikeout_tracker

                            # Generate ID unique for each play
                            info['id'] = ''.join(
                                [info['startTime'], ';', info['outs'], ';', info['inning'], ';', info['homeScore'], ';',
                                 info['awayScore'], ';', info['atBatIndex']])

                            # if ID is not in DB, record it and post update on Discord
                            if info['id'] not in ids_of_prev_events:
                                self._log_event(info['id'], game_date_str, info['description'])
                                ids_of_prev_events.add(info['id'])
                                msg = self.comment_on_discord_event(info)
                                if msg:
                                    await queue.put({'msg': msg, 'active_game': True, 'game_id': game['game_id']})

                    else:
                        logger.info("Novel game status %r — consider adding explicit handling.", game_status)
                        how_long_to_wait_in_sec = 30

                logger.info("Sleep is %s. Delay is %s.", how_long_to_wait_in_sec, constants.DELAY)
               
                logger.info("About to sleep")
                sleep_time = (time + timedelta(seconds=how_long_to_wait_in_sec) - datetime.now()).total_seconds()
                if sleep_time <= 0.1:
                    sleep_time = 0.1
                
                logger.info(f"Sleep Time {sleep_time}")
                await asyncio.sleep(sleep_time)
                time = datetime.now()

            # Should never reach here
            logger.warning("/*------------- End of Bot.run() -------------*/")
        except Exception:
            raise

    def read_settings(self):
        with open(SETTINGS_FILE) as data:
            settings = json.load(data)

            self.DB_FILE = settings.get('DB_FILE')
            if self.DB_FILE is None: return "Missing DB_FILE"

            self.TEAM_ID = settings.get('TEAM_ID')
            if self.TEAM_ID is None: return "Missing TEAM_ID"

            self.WIN_MESSAGES = settings.get('WIN_MESSAGES')  # optional: str or list[str]

        return 0

    def getTime(self):
        return datetime.today().strftime("%Y/%m/%d %H:%M:%S")

    def _init_db(self):
        with sqlite3.connect(self.DB_FILE) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS posted_events (
                event_id   TEXT PRIMARY KEY,
                game_date  TEXT NOT NULL,
                description TEXT,
                logged_at  TEXT NOT NULL
            )''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_game_date ON posted_events (game_date)')
            conn.execute('''CREATE TABLE IF NOT EXISTS game_threads (
                game_id   TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL
            )''')
            conn.execute('''CREATE TABLE IF NOT EXISTS game_events (
                game_id  TEXT PRIMARY KEY,
                event_id TEXT NOT NULL
            )''')
            self._prune_old_events(conn)

    def _prune_old_events(self, conn):
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y/%m/%d %H:%M:%S")
        conn.execute('DELETE FROM posted_events WHERE logged_at < ?', (cutoff,))

    def _load_todays_events(self, game_date: str) -> set:
        with sqlite3.connect(self.DB_FILE) as conn:
            rows = conn.execute(
                'SELECT event_id FROM posted_events WHERE game_date = ?', (game_date,)
            ).fetchall()
        return {row[0] for row in rows}

    def _log_event(self, event_id: str, game_date: str, description: str):
        with sqlite3.connect(self.DB_FILE) as conn:
            conn.execute(
                'INSERT OR IGNORE INTO posted_events (event_id, game_date, description, logged_at) VALUES (?, ?, ?, ?)',
                (event_id, game_date, description, self.getTime())
            )
        logger.info("Logged: %s", event_id)

    def getPlayType(self, description):
        if "Status Change" in description: return "statusChange"
        if "Mound Visit" in description: return "moundVisit"
        if "Pitching Change" in description: return "pitchingChange"
        if "Defensive Substitution" in description: return "defensiveSubstitution"
        if "Offensive Substitution" in description: return "offensiveSubstitution"
        if "remains in the game" in description: return "remainsInTheGame"
        if "Game Advisory" in description: return "gameAdvisory"
        if "Umpire Substitution" in description: return "umpireSubstitution"
        if "Injury Delay" in description: return "injuryDelay"
        return 'atBat'

    async def postNoGameStatusOnDiscord(self, queue):
        if constants.NO_GAME_STATUS_TITLE or constants.NO_GAME_STATUS_DESCRIPTION:
            game_status_embed = discord.Embed(title=constants.NO_GAME_STATUS_TITLE,
                                              description=constants.NO_GAME_STATUS_DESCRIPTION)
            game_status_post = constants.NO_GAME_STATUS_BODY
            if game_status_embed.title or game_status_embed.description:
                await queue.put({'msg': game_status_post, 'embed': game_status_embed, 'game_id': None})

    async def select_win_message(self, game):
        """Return the custom win message if TEAM_ID is in this game and won,
        else None (caller falls back to the default game-over embed)."""
        messages = self.WIN_MESSAGES
        if not messages:
            return None
        if game['home_id'] == self.TEAM_ID:
            our_score, opp_score, side = game['home_score'], game['away_score'], 'home'
        elif game['away_id'] == self.TEAM_ID:
            our_score, opp_score, side = game['away_score'], game['home_score'], 'away'
        else:
            return None
        try:
            if int(our_score) <= int(opp_score):
                return None
        except (TypeError, ValueError):
            return None
        if isinstance(messages, str):
            return messages
        if isinstance(messages, list) and messages:
            try:
                data = await asyncio.to_thread(
                    statsapi.get, 'game', {'gamePk': game['game_id']})
                game_number = data['gameData']['teams'][side]['record']['gamesPlayed']
            except (HTTPError, KeyError):
                return None  # fall back rather than guess
            return messages[game_number % len(messages)]
        return None

    async def postGameStatusOnDiscord(self, queue, game):
        game_status_embed = discord.Embed(title="Game Status Update".format(game['status']),
                                          description=game['status'])
        game_status_post = ""
        extras = {}

        active_game = False

        # Different embeds and posts for each status
        if game['status'] == 'Scheduled':
            await queue.put({'game_id': game['game_id']})
            game_status_embed = discord.Embed(title=constants.SCHEDULED_GAME_STATUS_TITLE,
                                              description=constants.SCHEDULED_GAME_STATUS_DESCRIPTION)
            game_status_post = constants.SCHEDULED_GAME_STATUS_BODY
        if game['status'] == 'Pre-Game':
            game_status_embed = discord.Embed(title=constants.PREGAME_TITLE, description=constants.PREGAME_DESCRIPTION)
            game_status_post = constants.PREGAME_BODY
        if game['status'] == 'Warm Up' or game['status'] == "Warmup":
            # pregamePost = "{:<3}: {} {} ({}-{} {})\n" \
            #               "{:<3}: {} {} ({}-{} {})".format(
            #     "away team", "away pitcher throwing hand",
            #     "away pitcher name", "away pitcher wins",
            #     "away pitcher losses", "away pitcher era",
            #     "home team", "home pitcher throwing hand",
            #     "home pitcher name", "home pitcher wins",
            #     "home pitcher losses", "home pitcher era")
            game_status_embed = discord.Embed(title=constants.WARMUP_TITLE,
                                              description=f"{constants.WARMUP_DESCRIPTION}\n\nDelay set to {constants.DELAY} seconds.")
            game_status_embed.set_image(url=str(constants.WARMUP_IMAGE))
            game_status_post = constants.WARMUP_BODY  # pregamePost
        # Specifically for Game Started (only goes first time game becomes "In Progress"
        if game['status'] == 'In Progress':
            game_status_embed = discord.Embed(title=constants.GAMESTARTED_TITLE,
                                              description=constants.GAMESTARTED_DESCRIPTION)
            game_status_post = constants.GAMESTARTED_BODY
            active_game = True
            extras['event_start'] = True
        if game['status'] == 'Delayed: Rain' or game['status'] == 'Delayed Start: Rain':
            game_status_embed = discord.Embed(title=constants.RAINDELAY_TITLE,
                                              description=constants.RAINDELAY_DESCRIPTION)
            game_status_post = constants.RAINDELAY_BODY
        if game['status'] == 'Completed Early: Rain':
            game_status_embed = discord.Embed(title=constants.COMPLETEDEARLYRAIN_TITLE,
                                              description=constants.COMPLETEDEARLYRAIN_DESCRIPTION)
            extras['event_end'] = True
            game_status_post = constants.COMPLETEDEARLYRAIN_BODY
        if game['status'] == 'Postponed':
            game_status_embed = discord.Embed(title=constants.POSTPONED_TITLE,
                                              description=constants.POSTPONED_DESCRIPTION)
            game_status_post = constants.POSTPONED_BODY
        if game['status'] == 'Game Over':
            win_msg = await self.select_win_message(game)
            if win_msg:
                game_status_embed = discord.Embed()   # empty -> not sent; message-only so link preview renders
                game_status_post = win_msg
            else:
                game_status_embed = discord.Embed(title=constants.GAMEOVER_TITLE,
                                                  description=constants.GAMEOVER_DESCRIPTION)
                game_status_post = constants.GAMEOVER_BODY
            extras['event_end'] = True
        if game['status'] == 'Final':
            game_status_embed = discord.Embed(title=constants.FINAL_TITLE, description=constants.FINAL_DESCRIPTION)
            game_status_post = constants.FINAL_BODY
            extras['event_end'] = True
        if game['status'] == 'Game Over: Tied':
            game_status_embed = discord.Embed(title=constants.GAMEOVERTIED_TITLE,
                                              description=constants.GAMEOVERTIED_DESCRIPTION)
            game_status_post = constants.GAMEOVERTIED_BODY
            extras['event_end'] = True
        if game['status'] == 'Final: Tied':
            game_status_embed = discord.Embed(title=constants.FINALTIED_TITLE,
                                              description=constants.FINALTIED_DESCRIPTION)
            game_status_post = constants.FINALTIED_BODY
            extras['event_end'] = True
        # await asyncio.sleep(15)
        if game_status_post or game_status_embed.title or game_status_embed.description:
            await queue.put({'msg': game_status_post, 'embed': game_status_embed, 'active_game': active_game,
                             'game_id': game['game_id'], 'extras': extras})

    def comment_on_discord_event(self, info):
        if info['playTypeActual'] == 'atBat':
            comment = self.formatGameEventForDiscord(info)
        else:
            comment = self.formatPlayerChangeForDiscord(info)
        return comment

    def formatGameEventForDiscord(self, info):
        return "```" \
               "{}\n" \
               "{}{}\n" \
               "```\n" \
               "{}" \
               "{}".format(self.formatLinescoreForDiscord(info)
                           if not self.gameEventInningBeforeCurrentLinescoreInning(info)
                           else self.formatLinescoreCatchingUpForDiscord(info),
                           self.formatPitchCount(info), info['description'],
                           self.funEmoji(info),
                           self.end_of_inning(info))

    def formatLinescoreForDiscord(self, info):
        return "{}   ┌───┬──┬──┬──┐\n" \
               "   {}     │{:<3}│{:>2}│{:>2}│{:>2}│\n" \
               "  {} {}    ├───┼──┼──┼──┤\n" \
               "{}   │{:<3}│{:>2}│{:>2}│{:>2}│\n" \
               "         └───┴──┴──┴──┘".format(
            self.formatInning(info),
            self.formatSecondBase(info['manOnSecond']),
            info['awayTeamAbbv'].upper(), info['awayStats_linescore']['runs'], info['awayStats_linescore']['hits'],
            info['awayStats_linescore']['errors'],
            self.formatThirdBase(info['manOnThird']), self.formatFirstBase(info['manOnFirst']),
            self.formatOuts(info['outs']),
            info['homeTeamAbbv'].upper(), info['homeStats_linescore']['runs'], info['homeStats_linescore']['hits'],
            info['homeStats_linescore']['errors']
        )

    def gameEventInningBeforeCurrentLinescoreInning(self, info):
        return True if int(info['inning']) < int(info['currentInning_linescore']) else False

    def formatLinescoreCatchingUpForDiscord(self, info):
        return "{}\n" \
               "\n" \
               "  BOT         CATCHING\n" \
               " BEHIND          UP\n" \
               "".format(
            self.formatInning(info)
        )

    def formatInning(self, info):
        return "{} {:>2}".format(info['inningHalf'].upper()[0:3], info['inning'])

    def formatOuts(self, outs):
        outOrOuts = " Outs"
        if outs == "1": outOrOuts = "  Out"
        return "".join([outs, outOrOuts])

    def formatFirstBase(self, runnerOnBaseStatus):
        return self.formatBase(runnerOnBaseStatus)

    def formatSecondBase(self, runnerOnBaseStatus):
        return self.formatBase(runnerOnBaseStatus)

    def formatThirdBase(self, runnerOnBaseStatus):
        return self.formatBase(runnerOnBaseStatus)

    def formatBase(self, baseOccupied):
        if baseOccupied:
            return "●"
        return "○"

    def formatPitchCount(self, info):
        if info['playType'] == 'atBat':
            return "On a {}-{} count, ".format(info['balls'], info['strikes'])
        else:
            return ""

    def end_of_inning(self, info):
        if info['outs'] == "3":
            end_of_inning_string = "```------ End of {} ------\n{}\n------ End of {} ------\n\nCurrent delay set to " \
                                   "{} seconds.```".format(
                self.formatInning(info), info['fullLinescoreString'], self.formatInning(info), constants.DELAY)
            pitcher_count = info.get('pitcherCount')
            if pitcher_count:
                end_of_inning_string = "{}\n```{}```".format(
                    end_of_inning_string, format_pitch_count_line(*pitcher_count))
            if info['inning'] == "7" and info['inningHalf'].upper()[0:3] == "TOP":
                end_of_inning_string = "{}\n{}".format(end_of_inning_string, constants.SEVENTH_INNING_STRETCH)
            return end_of_inning_string
        return ""

    def formatPlayerChangeForDiscord(self, info):
        return "```" \
               "{}\n" \
               "```\n" \
               "{}".format(info['description'],
                           self.end_of_inning(info))

    async def lookupTeamInfo(self, id):
        retry = 0
        while True:
            try:
                teamInfoList = await asyncio.to_thread(statsapi.lookup_team, id)
                break
            except HTTPError as e:
                logger.warning("HTTPError looking up team (HTTP %s): %s",
                               e.response.status_code if e.response is not None else '?',
                               e.response.text[:500] if e.response is not None else str(e))
                await asyncio.sleep(2 * retry + 1)
                if retry < 30:
                    retry += 1

        if len(teamInfoList) != 1:
            logger.info("Team id", id, "cannot be resolved to a single team")
            return
        return teamInfoList[0]

    def homeTeamBatting(self, info):
        return info['inningHalf'].upper()[0:3] == "BOT"

    def funEmoji(self, info):
        logger.info(info)
        emoji = ""

        ## Pitching emoji
        if info['strikes'] == '3':
            if self.homeTeamBatting(info):
                emoji = "{} K Tracker ({}): ".format(info['awayTeamName'], len(info['strikeoutTracker']['away']))
                for swingingStrikeout in info['strikeoutTracker']['away']:
                    if swingingStrikeout:
                        emoji = ''.join([emoji, constants.EMOTE_STRIKEOUT])
                    else:
                        emoji = ''.join([emoji, constants.EMOTE_STRIKEOUT_LOOKING])
            else:
                emoji = "{} K Tracker ({}): ".format(info['homeTeamName'], len(info['strikeoutTracker']['home']))
                for swingingStrikeout in info['strikeoutTracker']['home']:
                    if swingingStrikeout:
                        emoji = ''.join([emoji, constants.EMOTE_STRIKEOUT])
                    else:
                        emoji = ''.join([emoji, constants.EMOTE_STRIKEOUT_LOOKING])
            emoji = ''.join([emoji, '\n'])

        ## Batting emoji
        # Grand Slam
        if info['event'] == 'Home Run' and info['rbi'] == '4':  # "grand slam" in info['description']:
            emoji = ''.join([emoji, constants.EMOTE_GRAND_SLAM, "\n"])
        # Home Run
        elif info['event'] == 'Home Run' and info[
            'rbi'] != '4':  # ("homers" in info['description']) or ("home run" in info['description']):
            emoji = ''.join([emoji, constants.EMOTE_HOMERUN, "\n"])
        # RBIs
        for rbis in range(info['rbis']):
            emoji = ''.join([emoji, constants.EMOTE_RBI, " "])
        # Earned runs that are not RBIs
        for earnedRunsNotRBIs in range(info['runsEarned'] - info['rbis']):
            emoji = ''.join([emoji, constants.EMOTE_EARNED_RUN, " "])
        # Unearned runs
        for unearnedRunsNotRBIs in range(info['runsScored'] - info['runsEarned']):
            emoji = ''.join([emoji, constants.EMOTE_UNEARNED_RUN, " "])

        return emoji


if __name__ == '__main__':
    baseballUpdaterBot = BaseballUpdaterBotV2()
    baseballUpdaterBot.run()
