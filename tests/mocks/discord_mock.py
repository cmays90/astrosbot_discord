"""
Mock Discord bot for the test harness.

All async operations complete immediately; every Discord API call is
recorded in MockBot.event_log for inspection after the run.
"""
import itertools
import discord
from dataclasses import dataclass, field
from typing import Optional, Any

_id_counter = itertools.count(10_000)


def _next_id() -> int:
    return next(_id_counter)


def view_text(view) -> str:
    """Flatten all TextDisplay content in a LayoutView into one string so tests
    can assert on card copy."""
    if view is None:
        return ""
    parts = []

    def walk(item):
        content = getattr(item, 'content', None)
        if isinstance(content, str):
            parts.append(content)
        for child in getattr(item, 'children', []) or []:
            walk(child)

    for child in getattr(view, 'children', []) or []:
        walk(child)
    return "\n".join(parts)


class MockMessage:
    def __init__(self, channel_id: int, content=None, embed=None, view=None, poll=None, bot=None):
        self.id = _next_id()
        self.channel_id = channel_id
        self.content = content
        self.embed = embed
        self.view = view
        self.poll = poll
        self._bot = bot

    async def create_thread(self, name: str) -> "MockThread":
        thread = MockThread(name=name, bot=self._bot)
        self._bot._threads[thread.id] = thread
        self._bot._record('thread_created', {'name': name, 'parent_msg_id': self.id, 'thread_id': thread.id})
        return thread

    async def publish(self):
        self._bot._record('message_published', {'msg_id': self.id})

    async def delete(self):
        self._bot._record('message_deleted', {'msg_id': self.id})

    async def add_reaction(self, emoji):
        pass

    async def end_poll(self):
        self._bot._record('poll_ended', {'msg_id': self.id})
        return self

    async def edit(self, content=None, embed=None, view=None):
        self.content = content or self.content
        self.embed = embed or self.embed
        self.view = view or self.view


class MockThread:
    def __init__(self, name: str, bot: "MockBot"):
        self.id = _next_id()
        self.name = name
        self._bot = bot
        self.messages: list[MockMessage] = []

    async def send(self, content=None, embed=None, view=None, files=None) -> MockMessage:
        msg = MockMessage(self.id, content=content, embed=embed, view=view, bot=self._bot)
        self.messages.append(msg)
        self._bot._record('message_sent', {
            'thread_id': self.id,
            'thread_name': self.name,
            'content': content,
            'has_embed': embed is not None,
            'embed_title': embed.title if embed else None,
            'has_view': view is not None,
            'view_text': view_text(view),
            'file_count': len(files) if files else 0,
        })
        return msg

    async def edit(self, archived: bool = False, locked: bool = False):
        self._bot._record('thread_edited', {'thread_id': self.id, 'archived': archived, 'locked': locked})

    async def fetch_message(self, msg_id: int) -> MockMessage:
        for m in self.messages:
            if m.id == msg_id:
                return m
        return MockMessage(self.id, bot=self._bot)


class MockChannel:
    def __init__(self, channel_id: int, bot: "MockBot"):
        self.id = channel_id
        self._bot = bot
        self.messages: list[MockMessage] = []

    async def send(self, content=None, embed=None, view=None, poll=None) -> MockMessage:
        msg = MockMessage(self.id, content=content, embed=embed, view=view, poll=poll, bot=self._bot)
        self.messages.append(msg)
        self._bot._record('message_sent', {
            'channel_id': self.id,
            'content': content,
            'has_embed': embed is not None,
            'has_view': view is not None,
            'view_text': view_text(view),
            'has_poll': poll is not None,
        })
        return msg

    async def fetch_message(self, msg_id: int) -> MockMessage:
        for m in self.messages:
            if m.id == msg_id:
                return m
        return MockMessage(self.id, bot=self._bot)


class MockEvent:
    def __init__(self, name: str, bot: "MockBot"):
        self.id = _next_id()
        self.name = name
        self._bot = bot

    async def edit(self, status=None):
        self._bot._record('event_status_changed', {'event_id': self.id, 'status': str(status) if status else None})


class MockGuild:
    def __init__(self, guild_id: int, bot: "MockBot"):
        self.id = guild_id
        self._bot = bot

    async def active_threads(self) -> list[MockThread]:
        return list(self._bot._threads.values())

    async def create_scheduled_event(
        self, name, start_time, end_time, entity_type, privacy_level, location
    ) -> MockEvent:
        event = MockEvent(name=name, bot=self._bot)
        self._bot._events[event.id] = event
        self._bot._record('event_created', {'event_id': event.id, 'name': name, 'location': location})
        return event

    async def fetch_scheduled_event(self, event_id: int) -> Optional[MockEvent]:
        return self._bot._events.get(int(event_id))


class MockBot:
    """
    Fake discord.ext.commands.Bot.

    Pass this to Harness() as the discord backend for fully offline tests.
    Inspect .event_log after run() for assertions.
    """

    def __init__(
        self,
        guild_id: int = 99001,
        game_thread_channel_id: int = 99002,
        announcement_channel_id: int = 99003,
    ):
        self.guild_id = str(guild_id)
        self.game_thread_channel_id = str(game_thread_channel_id)
        self.announcement_channel_id = str(announcement_channel_id)
        # No token — mock only
        self.token = None

        self._threads: dict[int, MockThread] = {}
        self._events: dict[int, MockEvent] = {}
        self._channels: dict[int, MockChannel] = {
            game_thread_channel_id: MockChannel(game_thread_channel_id, self),
            announcement_channel_id: MockChannel(announcement_channel_id, self),
        }
        self.event_log: list[dict] = []

    # --- Discord API surface ---

    async def wait_until_ready(self):
        pass

    def get_channel(self, channel_id: int):
        ch = self._channels.get(channel_id)
        if ch is not None:
            return ch
        return self._threads.get(channel_id)

    def get_guild(self, guild_id: int) -> MockGuild:
        return MockGuild(guild_id, self)

    # --- Internal ---

    def _record(self, event_type: str, data: dict):
        self.event_log.append({'type': event_type, **data})

    # --- Test helpers ---

    def threads_created(self) -> list[dict]:
        return [e for e in self.event_log if e['type'] == 'thread_created']

    def events_created(self) -> list[dict]:
        return [e for e in self.event_log if e['type'] == 'event_created']

    def messages_to_threads(self) -> list[dict]:
        return [e for e in self.event_log if e['type'] == 'message_sent' and 'thread_id' in e]

    def assert_message_containing(self, substring: str):
        for entry in self.event_log:
            if entry['type'] == 'message_sent' and entry.get('content'):
                if substring in entry['content']:
                    return
        all_content = [e.get('content') for e in self.event_log if e['type'] == 'message_sent']
        raise AssertionError(
            f"No message containing {substring!r}.\nAll messages: {all_content}"
        )

    def summary(self) -> str:
        lines = []
        counts: dict[str, int] = {}
        for e in self.event_log:
            counts[e['type']] = counts.get(e['type'], 0) + 1
        for k, v in counts.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    def dump(self):
        for entry in self.event_log:
            print(entry)
