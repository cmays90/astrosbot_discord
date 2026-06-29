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
import json
import cards
import BaseballConsumerConstants as constants
import logging
import pytz

SETTINGS_FILE = './settings.json'

logger = logging.getLogger(__name__)

# Game statuses where lineups either don't exist yet or no longer matter, so we
# don't bother fetching/posting them.
_LINEUP_SKIP = {'Scheduled', 'Final', 'Game Over', 'Game Over: Tied',
                'Final: Tied', 'Completed Early: Rain', 'Postponed'}


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

                    # Post both teams' starting lineups once they're both set
                    # (happens during Pre-Game/Warmup). Only logs after a message
                    # is actually built, so it keeps retrying until lineups drop.
                    lineup_id = 'Lineups;{}'.format(game['game_id'])
                    if lineup_id not in ids_of_prev_events and game_status not in _LINEUP_SKIP:
                        retry = 0
                        while True:
                            try:
                                lineup_game_data = await asyncio.to_thread(
                                    statsapi.get, 'game', {'gamePk': game['game_id']}
                                )
                                break
                            except HTTPError as e:
                                logger.warning("HTTPError fetching lineups (HTTP %s): %s",
                                               e.response.status_code if e.response is not None else '?',
                                               e.response.text[:500] if e.response is not None else str(e))
                                await asyncio.sleep(2 * retry + 1)
                                if retry < 30:
                                    retry += 1
                        lineup_view = cards.lineup_card(lineup_game_data)
                        if lineup_view is not None:
                            await queue.put({'view': lineup_view, 'game_id': game['game_id']})
                            self._log_event(lineup_id, game_date_str, "Lineups")
                            ids_of_prev_events.add(lineup_id)

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
                            info['batterId'] = play.get('matchup', {}).get('batter', {}).get('id')
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

                            # Due-up for the team coming to bat (= the fielding
                            # side of the half that just ended). Rides the
                            # end-of-inning card built in build_event_items.
                            # Suppressed once the game is over — no one bats next.
                            info['dueUp'] = (
                                None if self.game_is_over(game_info)
                                else cards.due_up_rows(game_info, side=pitching_side)
                            )

                            # Batter now at the plate, shown on the at-bat card
                            # for plays that don't end the inning.
                            info['nowUp'] = cards.now_up_row(game_info)

                            # playType isn't working, do it yourself
                            info['playTypeActual'] = self.getPlayType(info['description'])

                            # True only when this play actually ended a plate
                            # appearance (a hit, out, walk, K, ...). Challenges,
                            # timeouts, and other interruptions don't qualify, so
                            # the at-bat card skips "Now up" for them.
                            info['endsPlateAppearance'] = bool(
                                play['about'].get('isComplete')
                                and play['result'].get('type') == 'atBat'
                            )

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
                                for q_item in self.build_event_items(info):
                                    q_item['game_id'] = game['game_id']
                                    await queue.put(q_item)

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
            await queue.put({'view': cards.no_game_card(), 'game_id': None})

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
        status = game['status']

        # Scheduled just signals the poster to create the thread/event — no card.
        if status == 'Scheduled':
            await queue.put({'game_id': game['game_id']})
            return

        item = {'game_id': game['game_id'], 'extras': {}}

        # Finished games (incl. rain-shortened) get the marquee final card. For a
        # win we also pass the celebration link through as a trailing message so
        # its GIF/video preview still renders (a V2 view can't carry one).
        if status in cards.FINAL_STATES:
            item['extras']['event_end'] = True
            item['view'] = cards.final_card(game, self.TEAM_ID)
            if status == 'Game Over':
                win_msg = await self.select_win_message(game)
                if win_msg:
                    item['msg'] = win_msg
            await queue.put(item)
            return

        # In-progress / pre-game / delay status cards.
        if status == 'Pre-Game':
            item['view'] = cards.status_card(game, constants.PREGAME_TITLE,
                                             constants.PREGAME_DESCRIPTION, constants.PREGAME_BODY)
        elif status in ('Warm Up', 'Warmup'):
            item['view'] = cards.status_card(
                game, constants.WARMUP_TITLE,
                "{}\n\nDelay set to {} seconds.".format(constants.WARMUP_DESCRIPTION, constants.DELAY),
                constants.WARMUP_BODY, accent=cards.RAIN_SLATE, image_url=str(constants.WARMUP_IMAGE))
        elif status == 'In Progress':
            item['view'] = cards.status_card(game, constants.GAMESTARTED_TITLE,
                                             constants.GAMESTARTED_DESCRIPTION,
                                             constants.GAMESTARTED_BODY, accent=cards.WIN_GREEN)
            item['active_game'] = True
            item['extras']['event_start'] = True
        elif status in ('Delayed: Rain', 'Delayed Start: Rain'):
            item['view'] = cards.status_card(game, constants.RAINDELAY_TITLE,
                                             constants.RAINDELAY_DESCRIPTION,
                                             constants.RAINDELAY_BODY, accent=cards.RAIN_SLATE)
        elif status == 'Postponed':
            item['view'] = cards.status_card(game, constants.POSTPONED_TITLE,
                                             constants.POSTPONED_DESCRIPTION,
                                             constants.POSTPONED_BODY, accent=cards.RAIN_SLATE)
        else:
            item['view'] = cards.status_card(game, "Game Status Update", status, "")

        await queue.put(item)

    def build_event_items(self, info):
        """Build the queue item(s) for one play: an at-bat / player-change card,
        plus an end-of-inning card when the third out lands. Only the first item
        carries active_game so the broadcast delay applies once per play."""
        info['funEmoji'] = self.funEmoji(info)
        if info['playTypeActual'] == 'atBat':
            atbat = {'view': cards.atbat_card(info), 'active_game': True}
            bases_img = cards.bases_image_path(info)
            if bases_img:
                atbat['bases_image'] = bases_img
            items = [atbat]
        else:
            items = [{'view': cards.player_change_card(info), 'active_game': True}]
        if info['outs'] == "3":
            eoi = {'view': cards.end_of_inning_card(info)}
            if info['inning'] == "7" and info['inningHalf'].upper()[0:3] == "TOP":
                eoi['msg'] = constants.SEVENTH_INNING_STRETCH
            items.append(eoi)
        return items

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

    @staticmethod
    def game_is_over(game_info):
        """True once the final out has landed (Game Over or Final). Walk-offs
        and extra-inning endings don't fall on a fixed inning, so we read the
        game's coded state rather than guessing from the inning number."""
        state = game_info.get('gameData', {}).get('status', {}).get('codedGameState')
        return state in ('O', 'F')

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
