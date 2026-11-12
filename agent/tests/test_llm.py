"""A6: клиент OpenAI-совместимого API против настоящего HTTP-сервера, поднятого в тесте."""

import socket
import threading
import time

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from app.llm import ChatModel, LlmError, model_from_env

MESSAGE = {"role": "assistant", "content": "Привет!"}


class Provider:
    def __init__(self):
        self.reply = (200, {"choices": [{"message": MESSAGE}]})
        self.delay = 0.0
        self.received: list[tuple[dict, str | None]] = []


@pytest.fixture(scope="module")
def server():
    provider = Provider()

    async def completions(request: Request):
        provider.received.append((await request.json(), request.headers.get("authorization")))
        if provider.delay:
            time.sleep(provider.delay)
        status, body = provider.reply
        return PlainTextResponse(body, status_code=status) if isinstance(body, str) else JSONResponse(body, status_code=status)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = Starlette(routes=[Route("/v1/chat/completions", completions, methods=["POST"])])
    instance = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    while not instance.started:
        time.sleep(0.02)
    yield provider, f"http://127.0.0.1:{port}/v1"
    instance.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def provider(server):
    provider, _ = server
    provider.reply, provider.delay, provider.received = (200, {"choices": [{"message": MESSAGE}]}), 0.0, []
    return provider


@pytest.fixture()
def model(server):
    return ChatModel(base_url=server[1], model="test-model", api_key="secret-key")


def test_sends_model_messages_tools_and_key(model, provider):
    tools = [{"type": "function", "function": {"name": "x", "description": "", "parameters": {"type": "object"}}}]
    assert model.complete([{"role": "user", "content": "Привет"}], tools, timeout=2) == MESSAGE
    payload, auth = provider.received[0]
    assert payload["model"] == "test-model" and payload["messages"][0]["content"] == "Привет"
    assert payload["tools"] == tools and auth == "Bearer secret-key"


def test_without_tools_and_key(server, provider):
    ChatModel(base_url=server[1], model="m").complete([], None, timeout=2)
    payload, auth = provider.received[0]
    assert "tools" not in payload and auth is None


@pytest.mark.parametrize("reply", [
    (500, "Internal Server Error"),
    (401, {"error": {"message": "bad key"}}),
    (200, "не json"),
    (200, {"choices": []}),
    (200, {"choices": [{"message": "строка"}]}),
    (200, {"nothing": 1}),
])
def test_bad_answers_raise_llm_error(model, provider, reply):
    provider.reply = reply
    with pytest.raises(LlmError):
        model.complete([], None, timeout=2)


def test_timeout_and_unreachable(model, provider):
    provider.delay = 1.0
    with pytest.raises(LlmError):
        model.complete([], None, timeout=0.3)
    with pytest.raises(LlmError):
        ChatModel(base_url="http://127.0.0.1:9", model="m").complete([], None, timeout=1)


@pytest.mark.parametrize("env, expected", [
    ({}, None),
    ({"LLM_PROVIDER": "mock"}, None),
    ({"LLM_PROVIDER": " "}, None),
    ({"LLM_PROVIDER": "OpenAI", "LLM_BASE_URL": "https://api.example.com/v1/", "LLM_MODEL": "m", "LLM_API_KEY": "k"},
     ChatModel(base_url="https://api.example.com/v1", model="m", api_key="k")),
])
def test_model_from_env(monkeypatch, env, expected):
    for name in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert model_from_env() == expected


@pytest.mark.parametrize("env, message", [
    ({"LLM_PROVIDER": "gigachat"}, "поддерживаются mock и openai"),
    ({"LLM_PROVIDER": "openai", "LLM_MODEL": "m"}, "LLM_BASE_URL"),
    ({"LLM_PROVIDER": "openai", "LLM_BASE_URL": "http://x"}, "LLM_MODEL"),
])
def test_incomplete_settings_fail_at_start(monkeypatch, env, message):
    for name in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        model_from_env()
