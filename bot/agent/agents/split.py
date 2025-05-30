# bot/agent/agents/split.py
# -*- coding: utf-8 -*-
"""
split_agent — «первый фильтр»: решает,
сколько в пользовательском сообщении самостоятельных операций,
и разбивает текст на части.

Результат пишет в state.parts = List[str]
"""

import json
from typing import List

from ..prompts import get_split_prompt
from ..utils import AgentState, openai_client, agent_logger


async def split_agent(state: AgentState) -> AgentState:
    agent_logger.info("[SPLIT] Entering split_agent")

    # если сплит уже был сделан (например, при повторных итерациях) — пропускаем
    if state.parts:
        agent_logger.info("[SPLIT] Parts already present, skipping")
        return state

    user_text = state.messages[0]["content"] if state.messages else ""
    prompt = get_split_prompt(user_text)

    try:
        resp = await openai_client.chat.completions.create(
            model="gpt-4.1-nano",  # ⚠️ поставьте свою «микро»-модель
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        choice = resp.choices[0].message
        agent_logger.debug(f"[SPLIT] Raw LLM answer:\n{choice.content}")

        data = json.loads(choice.content)
        parts: List[str] = [p.strip() for p in data.get("parts", []) if p.strip()]
        if not parts:
            # если LLM ничего не нашёл — оставляем оригинал одной частью
            parts = [user_text]

        state.parts = parts
        # для наглядности кладём в журнальные сообщения
        state.messages.append(
            {"role": "assistant", "content": f"Split into {len(parts)} part(s)"}
        )
        agent_logger.info(f"[SPLIT] Done → {len(parts)} parts")

    except Exception as e:
        agent_logger.exception(f"[SPLIT] Failed: {e}")
        # fallback — оставляем исходный текст одной частью
        state.parts = [user_text]

    return state
