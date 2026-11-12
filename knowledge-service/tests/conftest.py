import os
import time
from pathlib import Path

import jwt
import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
CONTRACTS = Path(os.environ.get("CONTRACTS_DIR", ROOT / "contracts"))
FIXTURES = Path(os.environ.get("FIXTURES_DIR", ROOT / "fixtures"))
SECRET = "test-only-knowledge-secret-at-least-32-bytes"


@pytest.fixture(autouse=True)
def service_environment(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("KB_DIR", str(DATA / "kb"))


@pytest.fixture
def token():
    def make(*, secret=SECRET, algorithm="HS256", omit=(), **overrides):
        claims = {
            "sub": "u_anna", "login": "intern_anna", "role": "intern",
            "team_id": "team_delivery", "exp": int(time.time()) + 3600,
        }
        claims.update(overrides)
        for key in omit:
            claims.pop(key, None)
        return jwt.encode(claims, secret, algorithm=algorithm)
    return make


@pytest.fixture
def raw_document():
    return (DATA / "kb" / "kb_absence_rules.md").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def registry():
    return Registry().with_resources([
        (path.name, Resource.from_contents(yaml.safe_load(path.read_text()), default_specification=DRAFT202012))
        for path in CONTRACTS.glob("*.yaml")
    ])


def validate(value, schema, registry):
    Draft202012Validator({"$ref": schema}, registry=registry, format_checker=FormatChecker()).validate(value)
