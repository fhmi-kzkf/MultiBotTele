"""
Context & Persona Engine — Sliding window context builder with persona injection.

Manages the context window that gets sent to the LLM:
  - Fetches the last N messages from chat_history (sliding window)
  - Injects the agent's persona as the system prompt
  - Formats messages in OpenAI-compatible format
  - Detects persona drift via hash comparison
"""

import logging
from typing import List, Dict, Optional

from core import database as db
from core.config_manager import AgentConfig

logger = logging.getLogger(__name__)

# Maximum number of messages in the context window (including system prompt)
MAX_CONTEXT_MESSAGES = 15

# Base system instruction prepended to all persona prompts
BASE_SYSTEM_INSTRUCTION = """INSTRUKSI PENTING:
- Kamu sedang berada di grup Telegram. Balas dengan natural seperti percakapan manusia biasa.
- JANGAN pernah menyebut bahwa kamu adalah AI, bot, atau asisten virtual.
- Gunakan bahasa yang sesuai dengan percakapan grup (campuran formal dan informal).
- Panjang balasan harus proporsional: pertanyaan singkat = jawaban singkat (1-2 kalimat).
- Sesekali gunakan emoji secukupnya, tapi jangan berlebihan.
- Jika ada pertanyaan teknis, jawab sesuai pengetahuanmu tapi tetap dalam karakter.
- JANGAN mengulangi apa yang sudah dikatakan orang lain di chat.
- Kalau konteksnya tidak jelas atau topiknya sudah selesai, kamu boleh tidak menjawab (balas dengan "[SKIP]").
"""


async def build_llm_payload(
    agent: AgentConfig,
    chat_id: int,
    extra_message: Optional[str] = None,
    context_limit: int = MAX_CONTEXT_MESSAGES - 1,
) -> List[Dict[str, str]]:
    """
    Build the complete messages array for the LLM API call.

    Structure:
      1. System prompt: BASE_SYSTEM_INSTRUCTION + agent persona
      2. Last N messages from chat_history (user/assistant roles)
      3. Optional extra message (e.g., direct human question)

    Args:
        agent: The agent configuration with persona prompt
        chat_id: The Telegram chat ID to fetch context from
        extra_message: Optional additional message to append
        context_limit: Max number of chat messages to include (default: 14)

    Returns:
        List of message dicts in OpenAI format
    """
    messages = []

    # 1. System prompt with persona
    system_prompt = f"{BASE_SYSTEM_INSTRUCTION}\n\nPERSONA KAMU:\n{agent.persona_prompt}"
    messages.append({
        "role": "system",
        "content": system_prompt,
    })

    # 2. Fetch sliding window context from database
    context = await db.get_context_window(chat_id, limit=context_limit)

    for msg in context:
        # Determine role: messages from this agent are "assistant", others are "user"
        sender_name = msg.get("sender_name", "Unknown")
        text = msg.get("text_content", "")
        is_human = msg.get("is_human", True)

        # Format: include sender name for context
        formatted_content = f"[{sender_name}]: {text}"

        # All context messages are "user" role (group conversation)
        # The agent's own messages are still "user" with their name
        messages.append({
            "role": "user",
            "content": formatted_content,
        })

    # 3. Optional extra message
    if extra_message:
        messages.append({
            "role": "user",
            "content": extra_message,
        })

    # 4. Final instruction to respond as the agent
    messages.append({
        "role": "user",
        "content": f"Sekarang giliranmu untuk merespon sebagai {agent.name}. "
                   f"Balas secara natural sesuai konteks percakapan di atas. "
                   f"HANYA tulis pesan balasanmu saja, tanpa awalan nama atau tanda kutip. "
                   f"Jika kamu merasa tidak perlu merespon, balas dengan '[SKIP]'.",
    })

    logger.debug(
        f"Built LLM payload for {agent.id}: "
        f"{len(messages)} messages, {sum(len(m['content']) for m in messages)} chars"
    )
    return messages


async def build_conversation_starter_payload(
    agent: AgentConfig,
    chat_id: int,
    topic_hint: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Build an LLM payload for starting a new conversation topic.
    Used by the scheduler for burst conversations.

    Args:
        agent: The agent configuration
        chat_id: The Telegram chat ID
        topic_hint: Optional topic to discuss

    Returns:
        List of message dicts in OpenAI format
    """
    messages = []

    system_prompt = (
        f"{BASE_SYSTEM_INSTRUCTION}\n\n"
        f"PERSONA KAMU:\n{agent.persona_prompt}\n\n"
        f"TUGAS: Kamu harus memulai atau melanjutkan percakapan di grup Telegram. "
        f"Jangan memulai dengan sapaan formal. Langsung ke topik yang menarik sesuai karaktermu."
    )
    messages.append({"role": "system", "content": system_prompt})

    # Include recent context to avoid repeating topics
    context = await db.get_context_window(chat_id, limit=10)
    for msg in context:
        sender_name = msg.get("sender_name", "Unknown")
        text = msg.get("text_content", "")
        messages.append({
            "role": "user",
            "content": f"[{sender_name}]: {text}",
        })

    # Topic instruction
    if topic_hint:
        prompt = (
            f"Mulai percakapan tentang: {topic_hint}. "
            f"Balas sebagai {agent.name}, langsung ke topik tanpa sapaan."
        )
    else:
        prompt = (
            f"Mulai percakapan baru yang menarik sesuai karaktermu sebagai {agent.name}. "
            f"Bisa tentang update terbaru di dunia crypto/Web3, pertanyaan untuk member lain, "
            f"atau opini tentang topik yang sedang trending. "
            f"Langsung ke topik, jangan pakai sapaan formal. "
            f"HANYA tulis pesan kamu saja."
        )

    messages.append({"role": "user", "content": prompt})

    return messages


def check_persona_drift(agent: AgentConfig, stored_hash: Optional[str]) -> bool:
    """
    Check if an agent's persona has changed since the last stored hash.

    Returns:
        True if the persona has drifted (hash mismatch).
    """
    if stored_hash is None:
        return True  # First time — needs initialization
    current_hash = agent.persona_hash()
    drifted = current_hash != stored_hash
    if drifted:
        logger.info(
            f"Persona drift detected for {agent.id}: "
            f"{stored_hash} → {current_hash}"
        )
    return drifted


def is_skip_response(response: str) -> bool:
    """Check if the LLM response is a skip signal."""
    return "[SKIP]" in response.upper() or response.strip() == ""
