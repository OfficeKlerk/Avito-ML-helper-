"""Проверка по схемам контракта B прямо из `contracts/` — единственного источника схем."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

BASE_URI = "file:///contracts/"
CONTRACTS_DIR = Path(os.environ.get("CONTRACTS_DIR") or Path(__file__).resolve().parents[2] / "contracts")


@cache
def _validator(schema: str) -> Draft202012Validator:
    registry = Registry().with_resources(
        (BASE_URI + path.name, Resource(contents=yaml.safe_load(path.read_text(encoding="utf-8")), specification=DRAFT202012))
        for path in CONTRACTS_DIR.glob("*.yaml")
    )
    return Draft202012Validator(
        {"$ref": f"{BASE_URI}b_agent.yaml#/components/schemas/{schema}"}, registry=registry, format_checker=FormatChecker()
    )


def errors(instance: Any, schema: str) -> list[str]:
    """Нарушения схемы `b_agent.yaml#/components/schemas/<schema>`; пустой список — всё в порядке."""
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<корень>'}: {e.message}" for e in _validator(schema).iter_errors(instance)
    ]
