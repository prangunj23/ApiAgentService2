from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentkit import ToolContext
from agentkit.agent import Agent
from agentkit.server import create_app
from agentkit.testing import FakeLLM, commit_files, make_remote, make_settings
from agentkit.workspace import Repo
from service2_agent.spec import SPEC
from service2_agent.tools import service1_change_context

# The Actions scripts in this repo, which service1_change_context reuses.
AGENT_SCRIPTS = Path(__file__).resolve().parents[2] / "agent"


@pytest.fixture(autouse=True)
def no_dependency_installs(monkeypatch):
    monkeypatch.setattr(Repo, "uv_sync", lambda self: None)


def test_info_describes_the_agent(tmp_path):
    info = TestClient(create_app(SPEC, make_settings(tmp_path), llm=FakeLLM())).get("/api/info").json()
    assert info["id"] == "service2"
    assert info["features"] == ["emails"]
    tools = {tool["name"]: tool["needs_confirmation"] for tool in info["tools"]}
    assert tools["send_email"] is True and tools["service1_change_context"] is False


def test_service1_change_context_reuses_the_impact_agent(tmp_path):
    origin = tmp_path / "origin"
    service1_seed = make_remote(origin, "prangunj23/ApiAgentService1", {"src/operation/app.py": '@v1.post("/numeric_op")\n'})
    service2_files = {f"agent/{name}": (AGENT_SCRIPTS / name).read_text() for name in ("impact_agent.py", "nim.py", "email_sender.py")}
    service2_files |= {
        "pyproject.toml": '[project]\nname = "consumer"\n',
        "src/consumer/app.py": "from operation import OperationClient\n",
        "tests/test_app.py": "def test_ok():\n    pass\n",
    }
    make_remote(origin, "prangunj23/ApiAgentService2", service2_files)

    agent = Agent(SPEC, make_settings(tmp_path / "data", git_base_url=str(origin)), llm=FakeLLM())
    agent.workspace.ensure_cloned()
    # The change lands after the agent cloned, so the tool has to fetch it.
    after = commit_files(service1_seed, {"src/operation/app.py": '@v1.post("/subtract")\n'}, "Rename endpoint")

    context = service1_change_context.fn(ToolContext(agent, "conversation"), message="Endpoint renamed")
    assert "# Message from the ApiAgentService1 agent\nEndpoint renamed" in context
    assert '+@v1.post("/subtract")' in context
    assert f"..{after})" in context
    assert "--- src/consumer/app.py ---" in context
