"""Tools specific to ApiAgentService2."""

import importlib.util
import os
import sys
import threading
from types import ModuleType

from agentkit import ToolContext, ToolError, string, tool
from agentkit.workspace import EMPTY_TREE

SERVICE1_REPO_NAME = "ApiAgentService1"
_import_lock = threading.Lock()


def load_impact_agent(ctx: ToolContext) -> ModuleType:
    """Load agent/impact_agent.py from this agent's own checkout, pointed at its ApiAgentService1 clone."""
    own = ctx.agent.workspace.own
    path = own.root / "agent" / "impact_agent.py"
    if not path.is_file():
        raise ToolError(f"{own.name} has no agent/impact_agent.py")
    with _import_lock:
        os.environ["SERVICE1_PATH"] = str(ctx.agent.workspace.repo(SERVICE1_REPO_NAME).root)
        if str(path.parent) not in sys.path:
            sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location("service2_impact_agent", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


@tool(
    "service1_change_context",
    "Load an ApiAgentService1 change for impact analysis: the diff between two commits, ApiAgentService1's source "
    "after the change, and this repo's source. Fetches ApiAgentService1 first.",
    {
        "after": string("ApiAgentService1 commit after the change. Defaults to its origin/main."),
        "before": string("Commit before the change. Defaults to the parent of `after`."),
        "message": string("Message from the ApiAgentService1 agent, if there is one."),
    },
    max_result_chars=80_000,
)
def service1_change_context(ctx: ToolContext, after: str = "", before: str = "", message: str = "") -> str:
    service1 = ctx.agent.workspace.repo(SERVICE1_REPO_NAME)
    if not service1.exists():
        raise ToolError(f"{service1.name} isn't cloned yet")
    service1.fetch()
    after_ref = after or f"origin/{service1.ref.branch}"
    if not service1.commit_exists(after_ref):
        raise ToolError(f"Unknown ApiAgentService1 commit {after_ref!r}")
    after_sha = service1.git("rev-parse", after_ref).strip()
    if before and not service1.commit_exists(before):
        raise ToolError(f"Unknown ApiAgentService1 commit {before!r}")
    if not before and service1.commit_exists(f"{after_sha}~1"):
        before = service1.git("rev-parse", f"{after_sha}~1").strip()

    impact = load_impact_agent(ctx)
    diff = impact.service1_diff(before, after_sha)
    if not diff.strip():
        return f"ApiAgentService1 has no changes between {before[:7] or 'the start'} and {after_sha[:7]}."
    event = {
        "message": message,
        "before": before,
        "after": after_sha,
        "contract_changes": [],
        "compare_url": f"https://github.com/{service1.slug}/compare/{before or EMPTY_TREE}...{after_sha}",
    }
    return impact.build_context(event, diff)
