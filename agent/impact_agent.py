# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "httpx>=0.27",
#     "markdown>=3.6",
#     "openai>=1.40",
# ]
# ///
"""ApiAgentService2 agent: assesses how an ApiAgentService1 change affects this service,
opens a PR with suggested fixes, and emails an update."""

import argparse
import json
import os
import subprocess
from pathlib import Path

import httpx
import markdown

from email_sender import send_email
from nim import chat_json

ROOT = Path(__file__).resolve().parent.parent
SERVICE1 = Path(os.environ.get("SERVICE1_PATH") or ROOT.parent / "ApiAgentService1")
REPO = os.environ.get("GITHUB_REPOSITORY", "prangunj23/ApiAgentService2")
SERVICE1_REPO = os.environ.get("SERVICE1_REPO", "prangunj23/ApiAgentService1")
BASE_BRANCH = os.environ.get("BASE_BRANCH", "main")
EDITABLE_DIRS = ("src", "tests")
EMPTY_TREE = "4b825dc642cb6eb9a060ae81c5c29fbd9e0f06a0"
MAX_DIFF_CHARS = 60_000

ANALYSIS_PROMPT = """You are the maintainer agent for ApiAgentService2, a FastAPI service that calls
ApiAgentService1 (the "operation" service) over HTTP using the `operation` Python package,
installed from the ApiAgentService1 repo.

The ApiAgentService1 agent has sent you a message about a change pushed to its main branch.
Using that message, the diff, and both codebases, work out how the change affects
ApiAgentService2: broken imports, renamed endpoints or methods, changed request or response
fields, behavior changes, or no effect at all.

Respond with only a JSON object:
{
  "severity": "none" | "minor" | "breaking",
  "impact_summary": "Markdown: what changed and how it affects ApiAgentService2",
  "affected_files": ["ApiAgentService2 paths that need changes"],
  "email_subject": "Short subject line",
  "email_body_markdown": "Markdown email to the ApiAgentService2 maintainer: what changed in ApiAgentService1, how it affects ApiAgentService2, and recommended next steps. Don't include links; they are added automatically."
}"""

FIX_PROMPT = """You are the maintainer agent for ApiAgentService2. A change to ApiAgentService1 affects
this service; the impact analysis is included below. Write the smallest set of changes to
ApiAgentService2 that makes it work with the new ApiAgentService1 and keeps its tests meaningful
and passing. Only edit files under src/ or tests/, match the existing code style, and don't
change ApiAgentService2's own API unless it is unavoidable.

Respond with only a JSON object, giving the complete new content of every file you change:
{
  "title": "Pull request title",
  "pr_body_markdown": "What you changed and why",
  "files": [{"path": "src/consumer/app.py", "content": "complete file content"}]
}"""


def run(*cmd: str, cwd: Path = ROOT) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def load_event(args: argparse.Namespace) -> dict:
    event: dict = {}
    if event_path := os.environ.get("GITHUB_EVENT_PATH"):
        data = json.loads(Path(event_path).read_text())
        event = dict(data.get("client_payload") or data.get("inputs") or {})
    for key in ("message", "before", "after"):
        if value := getattr(args, key):
            event[key] = value
    if not event.get("after"):
        raise SystemExit("No ApiAgentService1 commit to assess; pass --after or trigger via repository_dispatch.")

    if not event.get("before") or set(event["before"]) == {"0"}:
        event["before"] = ""
    event.setdefault("message", "")
    event.setdefault(
        "compare_url",
        f"https://github.com/{SERVICE1_REPO}/compare/{event['before'] or EMPTY_TREE}...{event['after']}",
    )
    return event


def service1_diff(before: str, after: str) -> str:
    diff = run("git", "diff", before or EMPTY_TREE, after, "--", ".", ":(exclude)uv.lock", cwd=SERVICE1)
    return diff[:MAX_DIFF_CHARS]


def service1_sources(after: str) -> str:
    paths = run("git", "ls-tree", "-r", "--name-only", after, "--", "src", cwd=SERVICE1).split()
    return "\n\n".join(
        f"--- {path} ---\n{run('git', 'show', f'{after}:{path}', cwd=SERVICE1)}"
        for path in paths
        if path.endswith(".py")
    )


def service2_sources() -> str:
    paths = [ROOT / "pyproject.toml", *sorted((ROOT / "src").rglob("*.py")), *sorted((ROOT / "tests").rglob("*.py"))]
    return "\n\n".join(f"--- {path.relative_to(ROOT)} ---\n{path.read_text()}" for path in paths)


def build_context(event: dict, diff: str) -> str:
    contract_changes = "\n".join(f"- {change}" for change in event.get("contract_changes", []))
    return f"""# Message from the ApiAgentService1 agent
{event['message']}

Contract changes reported:
{contract_changes or '- none reported'}

# ApiAgentService1 diff ({event['before'] or 'initial'}..{event['after']})
```diff
{diff}
```

# ApiAgentService1 source after the change
{service1_sources(event['after'])}

# ApiAgentService2 source (this repo)
{service2_sources()}
"""


def apply_files(files: list[dict]) -> dict[str, str | None]:
    """Write suggested files. Returns the original content of each changed path (None if new)."""
    originals: dict[str, str | None] = {}
    for item in files:
        rel = str(item.get("path", "")).strip().removeprefix("./")
        parts = Path(rel).parts
        target = (ROOT / rel).resolve()
        if not parts or parts[0] not in EDITABLE_DIRS or ".." in parts or not target.is_relative_to(ROOT):
            print(f"Skipping suggested change outside {'/, '.join(EDITABLE_DIRS)}/: {rel!r}")
            continue

        content = item.get("content", "")
        original = target.read_text() if target.exists() else None
        if original == content:
            continue
        originals[rel] = original
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return originals


def restore_files(originals: dict[str, str | None]) -> None:
    for rel, original in originals.items():
        target = ROOT / rel
        if original is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(original)


def run_tests() -> tuple[bool, str]:
    # Drop the agent's own virtualenv so `uv run` uses this project's environment.
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    result = subprocess.run(
        ["uv", "run", "pytest", "-q", "-p", "no:warnings"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    return result.returncode == 0, (result.stdout + result.stderr)[-3000:]


def github(method: str, path: str, **kwargs) -> httpx.Response:
    return httpx.request(
        method,
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
        **kwargs,
    )


def open_pull_request(branch: str, title: str, body: str, paths: list[str], draft: bool) -> str:
    if run("git", "status", "--porcelain", "--", "uv.lock").strip():
        paths = [*paths, "uv.lock"]
    run("git", "checkout", "-B", branch)
    run("git", "add", "--", *paths)
    run(
        "git",
        "-c", "user.name=github-actions[bot]",
        "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit", "-m", title,
    )
    run("git", "push", "--force", "origin", branch)

    response = github(
        "POST",
        f"/repos/{REPO}/pulls",
        json={"title": title, "head": branch, "base": BASE_BRANCH, "body": body, "draft": draft},
    )
    if response.status_code == 422:
        # A PR for this branch is already open; the force push above updated it.
        owner = REPO.split("/")[0]
        existing = github("GET", f"/repos/{REPO}/pulls", params={"head": f"{owner}:{branch}", "state": "open"})
        existing.raise_for_status()
        if existing.json():
            return existing.json()[0]["html_url"]
    response.raise_for_status()
    return response.json()["html_url"]


def pr_body(fix: dict, analysis: dict, event: dict, tests_passed: bool, test_output: str) -> str:
    status = "Passing" if tests_passed else "Failing, so this PR is a draft"
    return f"""{fix.get('pr_body_markdown', '')}

## Why
{analysis.get('impact_summary', '')}

## ApiAgentService1 change
{event['compare_url']}

## Tests
{status}

<details><summary>pytest output</summary>

```
{test_output}
```
</details>

_Opened automatically by the ApiAgentService2 impact agent._
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", help="message from the ApiAgentService1 agent")
    parser.add_argument("--before", help="ApiAgentService1 commit before the change")
    parser.add_argument("--after", help="ApiAgentService1 commit after the change")
    parser.add_argument(
        "--dry-run", action="store_true", help="apply and test fixes, then revert; don't open a PR or send email"
    )
    args = parser.parse_args()

    event = load_event(args)
    diff = service1_diff(event["before"], event["after"])
    if not diff.strip():
        print("ApiAgentService1 diff is empty; nothing to assess.")
        return
    context = build_context(event, diff)

    analysis = chat_json(ANALYSIS_PROMPT, context)
    severity = analysis.get("severity", "none")
    print(f"Severity: {severity}\n\n{analysis.get('impact_summary', '')}\n")

    status_lines = [f"- ApiAgentService1 changes: {event['compare_url']}"]
    if severity != "none":
        fix = chat_json(FIX_PROMPT, f"{context}\n# Impact analysis\n{json.dumps(analysis, indent=2)}")
        originals = apply_files(fix.get("files", []))
        if originals:
            tests_passed, test_output = run_tests()
            print(f"Suggested changes to: {', '.join(originals)}")
            print(f"Tests {'passed' if tests_passed else 'failed'}:\n{test_output}\n")
            test_status = "tests passing" if tests_passed else "draft, tests failing"

            if args.dry_run:
                restore_files(originals)
                print("[dry run] Reverted suggested changes; no PR opened.\n")
                status_lines.append(f"- Suggested fix PR: not opened in dry run ({test_status})")
            else:
                branch = f"agent/service1-{event['after'][:7]}"
                title = fix.get("title") or f"Adapt to ApiAgentService1 {event['after'][:7]}"
                body = pr_body(fix, analysis, event, tests_passed, test_output)
                pr_url = open_pull_request(branch, title, body, list(originals), draft=not tests_passed)
                print(f"Opened PR: {pr_url}")
                status_lines.append(f"- Suggested fix PR: {pr_url} ({test_status})")
        else:
            status_lines.append("- The agent didn't find code changes to suggest.")
    else:
        status_lines.append("- No changes needed in ApiAgentService2.")

    subject = analysis.get("email_subject") or "ApiAgentService1 changed"
    email_markdown = f"{analysis.get('email_body_markdown', '')}\n\n---\n\n" + "\n".join(status_lines)

    if args.dry_run:
        print(f"[dry run] Email not sent.\nSubject: {subject}\n\n{email_markdown}")
        return

    recipients = [address.strip() for address in os.environ.get("EMAIL_TO", "").split(",") if address.strip()]
    if not recipients:
        raise SystemExit("EMAIL_TO is not set; can't send the update email.")
    send_email(recipients, subject, email_markdown, markdown.markdown(email_markdown, extensions=["fenced_code"]))
    print(f"Emailed {', '.join(recipients)}: {subject}")


if __name__ == "__main__":
    main()
