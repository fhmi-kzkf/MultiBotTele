"""
Telegram Client Layer — Telethon MTProto session manager and event handlers.

Manages 5 concurrent Userbot sessions:
  - Session lifecycle (start/stop)
  - Message sending with typing simulation
  - New message event interception
  - Agent lock management for race condition prevention
"""

import os
import asyncio
import logging
from typing import Dict, Optional, Callable, Awaitable, List
from datetime import datetime

from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession
from dotenv import load_dotenv

from core import database as db
from core.config_manager import AppConfig, AgentConfig
from core.jitter import calculate_typing_delay

load_dotenv()
logger = logging.getLogger(__name__)

# Telethon API credentials (shared across all userbots)
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sessions")


class TelegramClientManager:
    """
    Manages multiple Telethon clients for the Userbot network.
    Each agent gets its own TelegramClient instance.
    """

    def __init__(self):
        self.clients: Dict[str, TelegramClient] = {}
        self.agent_locks: Dict[str, asyncio.Lock] = {}
        self._on_human_message: Optional[Callable] = None
        self._target_chat_id: Optional[int] = None
        self._our_user_ids: set = set()

    def set_human_message_handler(
        self, handler: Callable[[int, int, str, str], Awaitable[None]]
    ) -> None:
        """
        Register the callback for when a human sends a message.
        Handler signature: (chat_id, sender_id, sender_name, text) -> None
        """
        self._on_human_message = handler

    async def initialize(self, config: AppConfig) -> None:
        """
        Initialize Telethon clients for all configured agents.
        Does NOT start the clients — call start_all() separately.
        """
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        self._target_chat_id = config.global_settings.target_chat_id

        for agent in config.agents:
            if not agent.phone and not agent.session_string:
                logger.warning(f"Agent {agent.id} has no phone/session — skipping")
                continue

            try:
                # Use session string if available, otherwise file-based session
                if agent.session_string:
                    session = StringSession(agent.session_string)
                else:
                    session_path = os.path.join(SESSIONS_DIR, agent.id)
                    session = session_path

                client = TelegramClient(
                    session,
                    API_ID,
                    API_HASH,
                    device_model="Samsung Galaxy S24",
                    system_version="Android 14",
                    app_version="10.14.5",
                    lang_code="id",
                )

                self.clients[agent.id] = client
                self.agent_locks[agent.id] = asyncio.Lock()

                # Register event handler for incoming messages
                self._register_handlers(client, agent)

                logger.info(f"Client initialized for {agent.id} ({agent.name})")

            except Exception as e:
                logger.error(f"Failed to initialize client for {agent.id}: {e}")

    def _register_handlers(self, client: TelegramClient, agent: AgentConfig) -> None:
        """Register Telethon event handlers for a specific client."""

        @client.on(events.NewMessage())
        async def on_new_message(event):
            """Handle all new messages in the target chat."""
            try:
                # Only process messages from the target chat
                chat_id = event.chat_id
                if self._target_chat_id and chat_id != self._target_chat_id:
                    return

                # Skip empty messages
                if not event.message.text:
                    return

                sender = await event.get_sender()
                if not sender:
                    return

                sender_id = sender.id
                sender_name = getattr(sender, "first_name", "") or ""
                if getattr(sender, "last_name", ""):
                    sender_name += f" {sender.last_name}"
                sender_name = sender_name.strip() or f"User_{sender_id}"

                # Determine if message is from one of our bots
                is_our_bot = sender_id in self._our_user_ids

                # Store in chat history
                await db.insert_chat_message(
                    chat_id=chat_id,
                    message_id=event.message.id,
                    sender_id=sender_id,
                    sender_name=sender_name,
                    text_content=event.message.text,
                    is_human=not is_our_bot,
                )

                # If it's a human message, trigger the interrupt handler
                if not is_our_bot and self._on_human_message:
                    await self._on_human_message(
                        chat_id, sender_id, sender_name, event.message.text
                    )

            except Exception as e:
                logger.error(f"Error handling message in {agent.id}: {e}", exc_info=True)

    async def start_all(self) -> None:
        """Start all initialized Telethon clients."""
        for agent_id, client in self.clients.items():
            try:
                await client.start()
                me = await client.get_me()
                if me:
                    self._our_user_ids.add(me.id)
                    logger.info(
                        f"Client {agent_id} started — logged in as {me.first_name} "
                        f"(ID: {me.id})"
                    )

                    # Update agent session in DB
                    await db.upsert_agent_session(
                        agent_id=agent_id,
                        phone_number=me.phone or "",
                        is_active=True,
                    )
            except Exception as e:
                logger.error(f"Failed to start client {agent_id}: {e}", exc_info=True)

    async def stop_all(self) -> None:
        """Gracefully disconnect all Telethon clients."""
        for agent_id, client in self.clients.items():
            try:
                await client.disconnect()
                logger.info(f"Client {agent_id} disconnected")
            except Exception as e:
                logger.error(f"Error disconnecting {agent_id}: {e}")
        self.clients.clear()
        self.agent_locks.clear()
        self._our_user_ids.clear()

    async def send_message_with_typing(
        self,
        agent_id: str,
        chat_id: int,
        text: str,
        agent_config: AgentConfig,
    ) -> bool:
        """
        Send a message as a specific agent with realistic typing simulation.

        Steps:
          1. Acquire agent lock (prevent concurrent sends)
          2. Mark agent as typing in DB
          3. Send "typing" action to Telegram
          4. Wait for jitter-calculated delay
          5. Send the actual message
          6. Release lock and update DB

        Returns:
            True if message was sent successfully, False otherwise.
        """
        if agent_id not in self.clients:
            logger.error(f"No client for agent {agent_id}")
            return False

        client = self.clients[agent_id]
        lock = self.agent_locks.get(agent_id)
        if not lock:
            lock = asyncio.Lock()
            self.agent_locks[agent_id] = lock

        async with lock:
            try:
                # Mark as typing in DB
                await db.update_agent_state(agent_id, is_typing=True)

                # Calculate typing delay
                typing_delay = calculate_typing_delay(text, agent_config.typing_speed_wpm)
                logger.info(
                    f"Agent {agent_id} typing for {typing_delay:.1f}s before sending "
                    f"({len(text)} chars)"
                )

                # Send typing action to Telegram
                async with client.action(chat_id, "typing"):
                    await asyncio.sleep(typing_delay)

                # Send the actual message
                result = await client.send_message(chat_id, text)

                # Store our own message in chat history
                await db.insert_chat_message(
                    chat_id=chat_id,
                    message_id=result.id,
                    sender_id=(await client.get_me()).id,
                    sender_name=agent_config.name,
                    text_content=text,
                    is_human=False,
                )

                # Update agent state
                await db.update_agent_state(
                    agent_id,
                    is_typing=False,
                    last_message_timestamp=datetime.utcnow(),
                )

                logger.info(f"Agent {agent_id} sent message to chat {chat_id}")
                return True

            except Exception as e:
                logger.error(
                    f"Error sending message as {agent_id}: {e}", exc_info=True
                )
                # Ensure we clear the typing state on error
                await db.update_agent_state(agent_id, is_typing=False)
                return False

    async def send_read_acknowledge(self, agent_id: str, chat_id: int) -> None:
        """Mark messages as read for a specific agent (organic behavior)."""
        if agent_id not in self.clients:
            return
        try:
            client = self.clients[agent_id]
            await client.send_read_acknowledge(chat_id)
        except Exception as e:
            logger.debug(f"Failed to send read acknowledge for {agent_id}: {e}")

    def get_active_client_ids(self) -> List[str]:
        """Return list of agent IDs with active clients."""
        return list(self.clients.keys())

    def is_our_user(self, user_id: int) -> bool:
        """Check if a user ID belongs to one of our bots."""
        return user_id in self._our_user_ids
