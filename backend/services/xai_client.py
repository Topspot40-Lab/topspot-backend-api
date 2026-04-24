from __future__ import annotations

import logging
from typing import Any

import requests

from backend.config import XAI_API_KEY, XAI_API_URL, DEFAULT_XAI_MODEL

logger = logging.getLogger("XAI_CLIENT")


def ask_xai(system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    """
    Small synchronous XAI helper for maintenance scripts.
    """
    if not XAI_API_KEY:
        raise RuntimeError("XAI_API_KEY is missing. Check your .env file.")

    payload: dict[str, Any] = {
        "model": DEFAULT_XAI_MODEL,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    headers = {
        "Authorization": f"Bearer {XAI_API_KEY}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        XAI_API_URL,
        headers=headers,
        json=payload,
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    return data["choices"][0]["message"]["content"].strip()