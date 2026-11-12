"""Real Gunicorn agent + knowledge-service over HTTP. No LLM key or search mock."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import jwt
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(url, *, body=None, token=None):
    headers = {"Content-Type": "application/json", "X-Request-Id": "rq-integration-knowledge-001"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def main():
    processes, logs = [], []
    secret = secrets.token_hex(32)
    knowledge_port, agent_port = free_port(), free_port()
    while agent_port == knowledge_port:
        agent_port = free_port()
    knowledge_url, agent_url = f"http://127.0.0.1:{knowledge_port}", f"http://127.0.0.1:{agent_port}"
    common = {**os.environ, "JWT_SECRET": secret, "KB_DIR": str(ROOT / "data/kb"),
              "CONTRACTS_DIR": str(ROOT / "contracts"), "KNOWLEDGE_URL": knowledge_url,
              "MCP_URL": "http://127.0.0.1:1/mcp", "TOOL_TIMEOUT_SECONDS": "0.2", "LLM_PROVIDER": "mock"}
    try:
        for folder, port, url in [("knowledge-service", knowledge_port, knowledge_url), ("agent", agent_port, agent_url)]:
            log = tempfile.TemporaryFile(mode="w+t")
            logs.append(log)
            process = subprocess.Popen([sys.executable, "-m", "gunicorn", "--bind", f"127.0.0.1:{port}",
                                        "--workers", "2", "app:create_app()"], cwd=ROOT / folder,
                                       env=common, stdout=log, stderr=log)
            processes.append(process)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    if request(url + "/health")[0] == 200:
                        break
                except OSError:
                    time.sleep(.05)
            else:
                raise RuntimeError(f"{folder} startup timed out")
            if process.poll() is not None:
                log.seek(0)
                raise RuntimeError(log.read())
        users = {u["id"]: u for u in json.loads((ROOT / "data/seed/users.json").read_text())}
        def token(user_id, expires=None):
            user = users[user_id]
            return jwt.encode({"sub": user_id, "login": user["login"], "role": user["role"],
                               "team_id": user["team_id"], "exp": expires or int(time.time()) + 300}, secret, algorithm="HS256")
        # Import the original client, with no edits or fake transport.
        spec = importlib.util.spec_from_file_location("integration_agent_tools", ROOT / "agent/app/tools.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        tools = module.Tools(knowledge_url, common["MCP_URL"], token("u_anna"), "rq-integration-tools-001")
        result = tools.search("как оформить отгул")
        assert result[0]["source"]["chunk_id"] == "kb_absence_rules#day-off", result
        assert tools.trace[-1]["ok"]
        maximum = module.Tools(knowledge_url, common["MCP_URL"], token("u_max"), "rq-integration-tools-002")
        assert maximum.search("во сколько стендап в доставке") == []
        invalid = module.Tools(knowledge_url, common["MCP_URL"], token("u_anna", 1), "rq-integration-tools-003")
        try:
            invalid.search("отгул")
        except module.ToolError as exc:
            assert exc.code == "unauthorized"
        else:
            raise AssertionError("expired JWT accepted")
        status, denied = request(knowledge_url + "/v1/documents/kb_auto_release_process", token=token("u_anna"))
        assert status == 403 and denied == {"error": {"code": "forbidden", "message": "Нет доступа."}}
        body = copy.deepcopy(json.loads((ROOT / "fixtures/b_agent/chat.json").read_text())["cases"][0]["request"]["body"])
        body["message"] = "Во сколько стендап?"
        body["request_id"] = "rq-integration-chat-001"
        status, response = request(agent_url + "/v1/chat", body=body, token=token("u_anna"))
        assert status == 200 and "11:00" in response["text"], response
        assert any(s["chunk_id"] == "kb_delivery_rituals#standup" for s in response["sources"]), response
        registry = Registry().with_resources([(p.name, Resource.from_contents(yaml.safe_load(p.read_text()), default_specification=DRAFT202012)) for p in (ROOT / "contracts").glob("*.yaml")])
        Draft202012Validator({"$ref": "b_agent.yaml#/components/schemas/ChatResponse"}, registry=registry).validate(response)
        # Even a different team in the agent's JSON context cannot override the signed user.
        body["request_id"] = "rq-integration-chat-002"
        status, response = request(agent_url + "/v1/chat", body=body, token=token("u_max"))
        assert status == 200 and response["sources"] == [] and "11:00" not in response["text"], response
        print("PASS: real agent client search, ACL, expired JWT, direct-read denial, agent HTTP answer, signed-team isolation (6 checks).")
        print("Both services ran Gunicorn with 2 workers; no LLM or corporate service was used for the successful knowledge answer.")
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
