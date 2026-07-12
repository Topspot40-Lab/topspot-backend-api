from __future__ import annotations

import logging
import time
from typing import Any

import requests

from backend.config import XAI_API_KEY, XAI_API_URL, DEFAULT_XAI_MODEL

logger = logging.getLogger("XAI_CLIENT")


def ask_xai(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_attempts: int = 3,
) -> str:
    """
    Small synchronous XAI helper for maintenance scripts.

    Retries transient failures and allows extra time for long-form
    translation and narration requests.
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

    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(
                "Calling XAI model=%s attempt=%s/%s",
                DEFAULT_XAI_MODEL,
                attempt,
                max_attempts,
            )

            response = requests.post(
                XAI_API_URL,
                headers=headers,
                json=payload,
                timeout=(10, 300),
            )

            if response.status_code in {429, 500, 502, 503, 504}:
                raise requests.HTTPError(
                    f"Temporary XAI error {response.status_code}: "
                    f"{response.text[:500]}",
                    response=response,
                )

            if not response.ok:
                print("XAI ERROR STATUS:", response.status_code)
                print("XAI ERROR BODY:", response.text)
                response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()

            if not content:
                last_error = RuntimeError("XAI returned an empty response.")

                if attempt >= max_attempts:
                    break

                wait_seconds = attempt * 5
                print(
                    f"XAI attempt {attempt} returned an empty response.\n"
                    f"Retrying in {wait_seconds} seconds..."
                )
                time.sleep(wait_seconds)
                continue

            return content

        except (
            requests.Timeout,
            requests.ConnectionError,
            requests.HTTPError,
        ) as exc:
            last_error = exc

            if attempt >= max_attempts:
                break

            wait_seconds = attempt * 5
            print(
                f"XAI attempt {attempt} failed: {exc}\n"
                f"Retrying in {wait_seconds} seconds..."
            )
            time.sleep(wait_seconds)

    raise RuntimeError(
        f"XAI request failed after {max_attempts} attempts: {last_error}"
    ) from last_error
