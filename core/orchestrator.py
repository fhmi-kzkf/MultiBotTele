"""
Orchestrator & Queue Manager — The central brain of the Multi-Agent system.

Manages:
  - Priority queue (human interrupts > scheduled bursts)
  - Agent selection for responses (persona-based matching)
  - Conversation burst orchestration
  - State coordination across all components
"""

import asyncio
import random
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from core.config_manager import AppConfig, AgentConfig, get_config
from core.context_engine import (
    build_llm_payload,
    build_conversation_starter_payload,
    is_skip_response,
)
from core.llm_router import LlmRouter, LlmRouterError
from core.telegram_client import TelegramClientManager
from core.jitter import (
    calculate_inter_message_delay,
    is_within_active_hours,
    should_skip_message,
    pick_random_agents,
)
from core import database as db

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    The central orchestration engine.

    Coordinates all components:
      - Receives human interruptions from Telegram client
      - Manages scheduled conversation bursts
      - Routes messages through LLM → Telegram pipeline
      - Enforces kill switch, active hours, and agent locks
    """

    def __init__(
        self,
        telegram_manager: TelegramClientManager,
        llm_router: LlmRouter,
    ):
        self.telegram = telegram_manager
        self.llm = llm_router
        self._is_running = False
        self._human_queue: asyncio.Queue = asyncio.Queue()
        self._burst_lock = asyncio.Lock()
        self._processing_human = False

    async def start(self) -> None:
        """Start the orchestrator and begin processing queues."""
        self._is_running = True

        # Register the human message handler with the Telegram client
        self.telegram.set_human_message_handler(self._on_human_message)

        # Start the human interrupt processor
        asyncio.create_task(self._human_interrupt_processor())

        logger.info("Orchestrator started")

    async def stop(self) -> None:
        """Stop the orchestrator gracefully."""
        self._is_running = False
        # Drain the queue
        while not self._human_queue.empty():
            try:
                self._human_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        logger.info("Orchestrator stopped")

    # ── Human Interruption Handling ─────────────────────────────────

    async def _on_human_message(
        self, chat_id: int, sender_id: int, sender_name: str, text: str
    ) -> None:
        """
        Callback invoked by TelegramClientManager when a human sends a message.
        Enqueues the message for priority processing.
        """
        config = get_config()
        if config.global_settings.kill_switch:
            logger.debug("Kill switch active — ignoring human message")
            return

        if not is_within_active_hours(config):
            logger.debug("Outside active hours — ignoring human message")
            return

        logger.info(
            f"Human interrupt from {sender_name} (ID: {sender_id}) "
            f"in chat {chat_id}: {text[:50]}..."
        )

        await self._human_queue.put({
            "chat_id": chat_id,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "text": text,
            "timestamp": datetime.utcnow(),
        })

    async def _human_interrupt_processor(self) -> None:
        """
        Background task that processes human interruption queue.
        Runs continuously, waiting for human messages to appear.
        """
        logger.info("Human interrupt processor started")
        while self._is_running:
            try:
                # Wait for a human message (with timeout for shutdown check)
                try:
                    msg = await asyncio.wait_for(
                        self._human_queue.get(), timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue

                self._processing_human = True

                # Add a short delay before responding (organic behavior)
                await asyncio.sleep(random.uniform(3.0, 10.0))

                await self._respond_to_human(
                    chat_id=msg["chat_id"],
                    sender_name=msg["sender_name"],
                    text=msg["text"],
                )

                self._processing_human = False

            except Exception as e:
                logger.error(f"Error in human interrupt processor: {e}", exc_info=True)
                self._processing_human = False
                await asyncio.sleep(2.0)

    async def _respond_to_human(
        self, chat_id: int, sender_name: str, text: str
    ) -> None:
        """
        Select the most relevant agent and generate a response to a human message.
        """
        config = get_config()

        # Get active agents
        active_agents = config.get_active_agents()
        if not active_agents:
            logger.warning("No active agents to respond to human message")
            return

        # Select the best agent to respond
        responder = self._select_best_agent(active_agents, text)
        if not responder:
            logger.warning("No suitable agent found to respond")
            return

        logger.info(f"Selected {responder.id} ({responder.name}) to respond to {sender_name}")

        try:
            # Build LLM payload with the human's message in context
            messages = await build_llm_payload(
                agent=responder,
                chat_id=chat_id,
                extra_message=f"[{sender_name}] baru saja bertanya/berkata: {text}\n"
                              f"Respon secara natural sebagai {responder.name}.",
            )

            # Generate response
            response = await self.llm.generate_response(messages)

            # Check if LLM decided to skip
            if is_skip_response(response):
                logger.info(f"{responder.id} decided to skip responding")
                return

            # Send with typing simulation
            success = await self.telegram.send_message_with_typing(
                agent_id=responder.id,
                chat_id=chat_id,
                text=response,
                agent_config=responder,
            )

            if success:
                logger.info(f"{responder.id} responded to {sender_name}")

                # Force follow-up from multiple active agents
                if len(active_agents) > 1:
                    logger.info(f"Triggering chain follow-up responses from other agents (excluding {responder.id})")
                    # We pass control to _add_follow_up which will manage delays and multiple responses
                    await self._add_follow_up(
                        chat_id, config, exclude_agent=responder.id
                    )

        except LlmRouterError as e:
            logger.error(f"LLM failed to generate response: {e}")
        except Exception as e:
            logger.error(f"Error responding to human: {e}", exc_info=True)

    def _select_best_agent(
        self, agents: List[AgentConfig], text: str
    ) -> Optional[AgentConfig]:
        """
        Select the most relevant agent to respond based on keyword matching
        against their persona prompts.

        Falls back to weighted random selection if no strong match found.
        """
        if not agents:
            return None

        text_lower = text.lower()
        scores = []

        for agent in agents:
            # Check if agent has a Telegram client
            if agent.id not in self.telegram.clients:
                continue

            score = 0
            persona_lower = agent.persona_prompt.lower()

            # Simple keyword matching
            # Check for topic-related keywords in both the message and persona
            keywords = text_lower.split()
            for keyword in keywords:
                if len(keyword) > 3 and keyword in persona_lower:
                    score += 2

            # Bonus for agents with specific expertise matching
            expertise_maps = {
                "developer": ["developer", "dev", "code", "technical", "bug", "api"],
                "trader": ["trader", "trading", "chart", "analisis", "teknikal", "harga", "price"],
                "researcher": ["research", "defi", "protocol", "yield", "governance"],
                "newbie": ["apa itu", "bagaimana", "gimana", "cara", "pemula", "baru"],
                "enthusiast": ["bullish", "moon", "pump", "community", "komunitas"],
            }

            for role, triggers in expertise_maps.items():
                if any(t in persona_lower for t in [role]):
                    if any(t in text_lower for t in triggers):
                        score += 5

            scores.append((agent, score))

        # Sort by score
        scores.sort(key=lambda x: x[1], reverse=True)

        # If top score > 0, use that agent. Otherwise, random pick
        if scores and scores[0][1] > 0:
            return scores[0][0]

        # Weighted random: prefer agents who haven't spoken recently
        available = [a for a, _ in scores]
        return random.choice(available) if available else None

    # ── Scheduled Burst Conversations ───────────────────────────────

    async def run_scheduled_burst(self, chat_id: Optional[int] = None) -> None:
        """
        Execute a scheduled conversation burst.
        Picks 2-3 agents randomly and generates a natural conversation.

        Called by the scheduler at regular intervals.
        """
        config = get_config()

        # Safety checks
        if config.global_settings.kill_switch:
            logger.debug("Kill switch active — skipping burst")
            return

        if not is_within_active_hours(config):
            logger.debug("Outside active hours — skipping burst")
            return

        if self._processing_human:
            logger.debug("Processing human interrupt — delaying burst")
            return

        target_chat = chat_id or config.global_settings.target_chat_id
        if not target_chat:
            logger.warning("No target chat ID configured — skipping burst")
            return

        active_agents = config.get_active_agents()
        available_agents = [
            a for a in active_agents if a.id in self.telegram.clients
        ]

        if len(available_agents) < 2:
            logger.warning("Not enough active agents for a burst")
            return

        async with self._burst_lock:
            try:
                # Pick random agents for this burst
                selected_ids = pick_random_agents(
                    [a.id for a in available_agents],
                    min_count=2,
                    max_count=min(4, len(available_agents)),
                )
                selected_agents = [
                    a for a in available_agents if a.id in selected_ids
                ]

                logger.info(
                    f"Starting burst with {len(selected_agents)} agents: "
                    f"{[a.name for a in selected_agents]}"
                )

                # First agent starts the conversation
                starter = selected_agents[0]
                messages = await build_conversation_starter_payload(
                    agent=starter, chat_id=target_chat
                )
                response = await self.llm.generate_response(messages)

                if is_skip_response(response):
                    logger.info("Burst starter decided to skip — aborting burst")
                    return

                # Send the opening message
                success = await self.telegram.send_message_with_typing(
                    agent_id=starter.id,
                    chat_id=target_chat,
                    text=response,
                    agent_config=starter,
                )

                if not success:
                    logger.error("Failed to send burst starter message")
                    return

                # Other agents respond in sequence
                for agent in selected_agents[1:]:
                    # Check for human interrupts
                    if not self._human_queue.empty():
                        logger.info("Human interrupt detected — pausing burst")
                        break

                    # Check kill switch
                    config = get_config()
                    if config.global_settings.kill_switch:
                        logger.info("Kill switch activated during burst — stopping")
                        break

                    # Random chance to skip (10%)
                    if should_skip_message():
                        logger.debug(f"{agent.name} decided to skip in burst")
                        continue

                    # Inter-message delay
                    delay = calculate_inter_message_delay()
                    logger.debug(f"Waiting {delay:.1f}s before {agent.name}'s turn")
                    await asyncio.sleep(delay)

                    # Generate response
                    try:
                        messages = await build_llm_payload(
                            agent=agent, chat_id=target_chat
                        )
                        response = await self.llm.generate_response(messages)

                        if is_skip_response(response):
                            logger.debug(f"{agent.name} skipped in burst")
                            continue

                        await self.telegram.send_message_with_typing(
                            agent_id=agent.id,
                            chat_id=target_chat,
                            text=response,
                            agent_config=agent,
                        )

                    except LlmRouterError as e:
                        logger.error(f"LLM error during burst for {agent.id}: {e}")
                        break

                logger.info("Burst conversation completed")

            except Exception as e:
                logger.error(f"Error during scheduled burst: {e}", exc_info=True)

    async def _add_follow_up(
        self, chat_id: int, config: AppConfig, exclude_agent: str
    ) -> None:
        """Add follow-up messages from multiple different agents sequentially."""
        active_agents = [
            a for a in config.get_active_agents()
            if a.id != exclude_agent and a.id in self.telegram.clients
        ]

        if not active_agents:
            logger.warning(f"No other active agents available for follow-up (excluding {exclude_agent})")
            return

        # Determine how many agents should follow up
        # High chance for all remaining agents to join the conversation to simulate crowd excitement
        num_followers = random.choices([1, 2, 3, 4], weights=[10, 20, 30, 40])[0]
        num_followers = min(num_followers, len(active_agents))

        followers = random.sample(active_agents, num_followers)
        logger.info(f"Selected {num_followers} follower agents to join the chat: {[f.name for f in followers]}")

        for follower in followers:
            try:
                # Add delay before each follow up to simulate human typing gap
                delay = calculate_inter_message_delay()
                await asyncio.sleep(delay)

                messages = await build_llm_payload(agent=follower, chat_id=chat_id)
                response = await self.llm.generate_response(messages)

                if not is_skip_response(response):
                    await self.telegram.send_message_with_typing(
                        agent_id=follower.id,
                        chat_id=chat_id,
                        text=response,
                        agent_config=follower,
                    )
                    logger.info(f"Follow-up message sent by {follower.name}")
                else:
                    logger.info(f"Follower {follower.name} decided to skip follow-up")
            except Exception as e:
                logger.error(f"Follow-up from {follower.name} failed: {e}", exc_info=True)

    # ── Kill Switch ─────────────────────────────────────────────────

    async def activate_kill_switch(self) -> None:
        """
        Emergency halt: stop all activity immediately.
        """
        logger.warning("🚨 KILL SWITCH ACTIVATED — Halting all activity")
        self._is_running = False

        # Clear the human queue
        while not self._human_queue.empty():
            try:
                self._human_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Deactivate all agents in DB
        await db.set_all_agents_inactive()
        logger.warning("All agents set to inactive")

    async def deactivate_kill_switch(self) -> None:
        """Resume operations after kill switch."""
        logger.info("Kill switch deactivated — resuming operations")
        self._is_running = True
        await db.set_all_agents_active()

        # Restart the human interrupt processor
        asyncio.create_task(self._human_interrupt_processor())

    def get_status(self) -> Dict[str, Any]:
        """Get current orchestrator status for the dashboard."""
        return {
            "is_running": self._is_running,
            "processing_human": self._processing_human,
            "human_queue_size": self._human_queue.qsize(),
            "active_clients": self.telegram.get_active_client_ids(),
        }


def calculate_inter_message_delay() -> float:
    """Import from jitter module — convenience re-export."""
    from core.jitter import calculate_inter_message_delay as _calc
    return _calc()
