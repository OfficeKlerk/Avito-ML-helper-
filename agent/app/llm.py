"""Клиент OpenAI-совместимого API Chat Completions с вызовом инструментов (задача A6)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LlmError(Exception):
    """Модель не ответила или ответила не по протоколу."""


@dataclass(frozen=True)
class ChatModel:
    base_url: str
    model: str
    api_key: str = ""

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, timeout: float) -> dict[str, Any]:
        """Сообщение ассистента: `content` и, если модель вызывает инструменты, `tool_calls`."""
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0.2}
        if tools:
            payload["tools"] = tools
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(payload).encode(),
                                         headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.load(response)
            message = body["choices"][0]["message"]
        except urllib.error.HTTPError as exc:
            # Текст ошибки провайдера в лог не тащим: в нём бывает эхо запроса.
            raise LlmError(f"модель ответила HTTP {exc.code}") from exc
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise LlmError(f"модель недоступна: {exc.__class__.__name__}") from exc
        if not isinstance(message, dict):
            raise LlmError("модель вернула сообщение не того формата")
        return message


def model_from_env() -> ChatModel | None:
    """None — режим без модели. Неполная настройка — ошибка при старте, а не тихий откат."""
    provider = os.environ.get("LLM_PROVIDER", "mock").strip().lower() or "mock"
    if provider == "mock":
        return None
    if provider != "openai":
        raise ValueError(f"LLM_PROVIDER={provider!r}: поддерживаются mock и openai")
    missing = [name for name in ("LLM_BASE_URL", "LLM_MODEL") if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError(f"LLM_PROVIDER=openai, но не заданы: {', '.join(missing)}")
    return ChatModel(
        base_url=os.environ["LLM_BASE_URL"].strip().rstrip("/"),
        model=os.environ["LLM_MODEL"].strip(),
        api_key=os.environ.get("LLM_API_KEY", "").strip(),
    )
