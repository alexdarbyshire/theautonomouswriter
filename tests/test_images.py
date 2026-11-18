import base64
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.error import HTTPError

import pytest

from agent.images import generate_cover_image

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 24
WEBP = b"RIFF" + (24).to_bytes(4, "little") + b"WEBPVP8 " + b"\0" * 16
MODELS = {
    "openai/gpt-image-2.5-sunburst",
    "microsoft/mai-image-2.7",
    "google/gemini-nano-banana-2.1",
}


def image_response(data, media_type=None):
    image = {"b64_json": base64.b64encode(data).decode()}
    if media_type is not None:
        image["media_type"] = media_type
    return {"data": [image]}


@pytest.fixture
def cover_run(monkeypatch):
    monkeypatch.setenv("ENABLE_IMAGES", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "offline-key")
    llm = MagicMock()
    llm.model = "writer-model"
    llm._call.return_value = "A misty cathedral at dawn"
    llm.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="1"))]
    )
    requests = []
    responses = {model: image_response(PNG, "image/png") for model in MODELS}

    def respond(request, timeout):
        assert timeout == 120
        requests.append(request)
        response = responses[json.loads(request.data)["model"]]
        if isinstance(response, Exception):
            raise response
        return BytesIO(json.dumps(response).encode())

    monkeypatch.setattr("urllib.request.urlopen", respond)
    return llm, requests, responses


def test_selected_models_use_images_api_and_preserve_jpeg(cover_run):
    llm, requests, responses = cover_run
    for model in MODELS:
        responses[model] = {"error": {"message": "generation failed"}}
    responses["microsoft/mai-image-2.7"] = image_response(JPEG, "image/jpeg")

    image = generate_cover_image(llm, "Title", "Description", "curious")

    assert image is not None
    assert image.data == JPEG
    assert image.mime_type == "image/jpeg"
    assert image.extension == "jpg"
    assert len(requests) == 3
    assert {json.loads(request.data)["model"] for request in requests} == MODELS
    for request in requests:
        assert request.full_url == "https://openrouter.ai/api/v1/images"
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer offline-key"
        assert request.get_header("Content-type") == "application/json"
        assert json.loads(request.data)["prompt"] == "A misty cathedral at dawn"
    llm.client.chat.completions.create.assert_not_called()


def test_judge_receives_original_formats_and_selects_candidate(cover_run):
    llm, _, responses = cover_run
    formats = [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")]
    for model, (data, mime) in zip(sorted(MODELS), formats, strict=True):
        responses[model] = image_response(data, mime)
    llm.client.chat.completions.create.return_value.choices[0].message.content = "2"
    image = generate_cover_image(llm, "Title", "Description", "curious")
    call = llm.client.chat.completions.create.call_args.kwargs
    urls = [item["image_url"]["url"] for item in call["messages"][0]["content"][1:]]
    assert set(urls) == {f"data:{mime};base64,{base64.b64encode(data).decode()}" for data, mime in formats}
    assert urls[1] == f"data:{image.mime_type};base64,{base64.b64encode(image.data).decode()}"
    assert call["model"] == "writer-model"
    assert call["extra_body"] == {"reasoning": {"effort": "low"}}


@pytest.mark.parametrize(
    "bad",
    [
        {"data": []},
        {},
        {"data": [{"b64_json": "!invalid"}]},
        image_response(b"not an image"),
        image_response(PNG, "image/jpeg"),
        HTTPError("https://example.invalid", 503, "unavailable", {}, None),
    ],
)
def test_failed_candidates_keep_successful_original_bytes(cover_run, bad):
    llm, _, responses = cover_run
    for model in MODELS:
        responses[model] = bad
    responses["microsoft/mai-image-2.7"] = image_response(WEBP)
    image = generate_cover_image(llm, "Title", "Description", "curious")
    assert image.data == WEBP
    assert image.extension == "webp"
    llm.client.chat.completions.create.assert_not_called()


def test_all_failures_allow_no_cover(cover_run):
    llm, _, responses = cover_run
    for model in MODELS:
        responses[model] = {}
    assert generate_cover_image(llm, "Title", "Description", "curious") is None


@pytest.mark.parametrize("reply", ["not a number", "99", RuntimeError("judge unavailable")])
def test_judge_failure_uses_first_completed_success(cover_run, reply):
    llm, _, _ = cover_run
    if isinstance(reply, Exception):
        llm.client.chat.completions.create.side_effect = reply
    else:
        llm.client.chat.completions.create.return_value.choices[0].message.content = reply
    image = generate_cover_image(llm, "Title", "Description", "curious")
    assert image.data == PNG


def test_disabled_images_call_no_services(cover_run, monkeypatch):
    llm, requests, _ = cover_run
    monkeypatch.setenv("ENABLE_IMAGES", "false")
    assert generate_cover_image(llm, "Title", "Description", "curious") is None
    assert requests == []
    llm._call.assert_not_called()
