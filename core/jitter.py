"""
Jitter Engine — Human-like typing delay and burst timing calculator.

Simulates organic behavior to prevent Telegram anti-spam detection:
  - Typing speed variation based on text length
  - Random burst delays between conversation bursts
  - Active hours enforcement
"""

import random
import logging
from datetime import datetime, time
from typing import Tuple

from core.config_manager import AppConfig, TypingSpeedRange

logger = logging.getLogger(__name__)


def calculate_typing_delay(text: str, wpm_range: TypingSpeedRange) -> float:
    """
    Calculate a realistic typing delay in seconds based on text length
    and a randomized WPM within the agent's range.

    Average English word ≈ 5 characters.
    Adds jitter: ±15% random variation + a small "thinking" pause.

    Args:
        text: The message text to be "typed"
        wpm_range: The agent's typing speed range (min/max WPM)

    Returns:
        Total delay in seconds before the message should be sent
    """
    if not text:
        return random.uniform(1.0, 3.0)

    # Pick a random WPM within the agent's range
    wpm = random.uniform(wpm_range.min, wpm_range.max)

    # Calculate base word count (avg 5 chars per word)
    word_count = max(1, len(text) / 5.0)

    # Base typing time in seconds
    base_seconds = (word_count / wpm) * 60.0

    # Add jitter: ±15% variation
    jitter_factor = random.uniform(0.85, 1.15)
    typing_seconds = base_seconds * jitter_factor

    # Add "thinking" pause: 1-5 seconds before typing starts
    thinking_pause = random.uniform(1.0, 5.0)

    # Add occasional longer pauses (10% chance of 3-8 extra seconds)
    extra_pause = random.uniform(3.0, 8.0) if random.random() < 0.10 else 0.0

    total_delay = thinking_pause + typing_seconds + extra_pause

    # Clamp: minimum 2 seconds, maximum 45 seconds
    total_delay = max(2.0, min(total_delay, 45.0))

    logger.debug(
        f"Jitter: text_len={len(text)}, wpm={wpm:.0f}, "
        f"base={base_seconds:.1f}s, total={total_delay:.1f}s"
    )
    return total_delay


def calculate_burst_delay(config: AppConfig) -> float:
    """
    Calculate a random delay between conversation bursts.
    Uses the configured min/max burst delay range.

    Returns:
        Delay in seconds.
    """
    delay_range = config.global_settings.burst_delay_minutes
    delay_minutes = random.uniform(delay_range.min, delay_range.max)

    # Add micro-jitter: ±2 minutes
    jitter = random.uniform(-2.0, 2.0)
    delay_minutes = max(5.0, delay_minutes + jitter)

    delay_seconds = delay_minutes * 60.0
    logger.debug(f"Burst delay: {delay_minutes:.1f} minutes ({delay_seconds:.0f}s)")
    return delay_seconds


def calculate_inter_message_delay() -> float:
    """
    Calculate a short delay between consecutive messages within a burst.
    Simulates a natural conversation pace between multiple bots.

    Returns:
        Delay in seconds (typically 8-60 seconds).
    """
    # Base delay: 8-30 seconds
    base = random.uniform(8.0, 30.0)

    # Occasional longer pause (20% chance): reading/thinking about previous message
    if random.random() < 0.20:
        base += random.uniform(15.0, 45.0)

    return base


def parse_time(time_str: str) -> time:
    """Parse an HH:MM time string into a datetime.time object."""
    parts = time_str.split(":")
    return time(int(parts[0]), int(parts[1]))


def is_within_active_hours(config: AppConfig) -> bool:
    """
    Check if the current time is within the configured active hours.

    Returns:
        True if the system should be active right now.
    """
    now = datetime.now().time()
    start = parse_time(config.global_settings.active_hours.start)
    end = parse_time(config.global_settings.active_hours.end)

    # Handle wrap-around (e.g., start=22:00, end=06:00)
    if start <= end:
        is_active = start <= now <= end
    else:
        is_active = now >= start or now <= end

    logger.debug(
        f"Active hours check: now={now}, range={start}-{end}, active={is_active}"
    )
    return is_active


def should_skip_message() -> bool:
    """
    Randomly decide if a bot should skip responding (to feel more organic).
    10% chance of skipping to avoid constant engagement.
    """
    return random.random() < 0.10


def pick_random_agents(agent_ids: list, min_count: int = 2, max_count: int = 4) -> list:
    """
    Randomly pick a subset of agents for a conversation burst.
    """
    count = random.randint(min(min_count, len(agent_ids)), min(max_count, len(agent_ids)))
    return random.sample(agent_ids, count)
