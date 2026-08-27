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
        timeout=(10, 180),
    )

    if not response.ok:
        status_code = getattr(response, "status_code", None)
        safe_status_code = status_code if type(status_code) is int else None
        error_label = "xAI request failed"
        if safe_status_code is not None:
            error_label = f"{error_label} (HTTP {safe_status_code})"
        print(error_label)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise requests.HTTPError(error_label, response=exc.response) from None

    data = response.json()

    return data["choices"][0]["message"]["content"].strip()
