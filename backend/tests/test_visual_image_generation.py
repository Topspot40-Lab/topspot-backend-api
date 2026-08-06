from __future__ import annotations

import base64
from unittest.mock import patch

import pytest
import requests

from backend.studio.visuals import generate_images


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self.payload = payload
        self.ok = 200 <= status_code < 300
        self.text = str(payload)

    def json(self) -> dict[str, object]:
        return self.payload

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(
                f"{self.status_code} error",
                response=self,
            )


def test_content_moderation_retries_once_with_safe_prompt() -> None:
    image = b"generated-image"
    responses = [
        FakeResponse(
            400,
            {"code": "imagine:content-moderated"},
        ),
        FakeResponse(
            200,
            {
                "data": [
                    {
                        "b64_json": base64.b64encode(image).decode("ascii"),
                    }
                ]
            },
        ),
    ]

    with (
        patch.object(generate_images, "XAI_API_KEY", "test-key"),
        patch.object(
            generate_images.requests,
            "post",
            side_effect=responses,
        ) as post,
    ):
        assert generate_images.generate_image("rejected prompt") == image

    assert post.call_count == 2
    assert post.call_args_list[0].kwargs["json"]["prompt"] == "rejected prompt"
    assert (
        post.call_args_list[1].kwargs["json"]["prompt"]
        == generate_images.MODERATION_SAFE_PROMPT
    )


def test_other_bad_request_is_not_retried() -> None:
    response = FakeResponse(400, {"code": "invalid-request"})

    with (
        patch.object(generate_images, "XAI_API_KEY", "test-key"),
        patch.object(
            generate_images.requests,
            "post",
            return_value=response,
        ) as post,
        pytest.raises(requests.HTTPError),
    ):
        generate_images.generate_image("invalid prompt")

    assert post.call_count == 1
