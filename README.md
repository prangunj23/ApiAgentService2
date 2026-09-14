# consumer (ApiAgentService2)

A downstream service that calls the `operation` service (ApiAgentService1). It uses the typed client `operation.OperationClient`, which it installs from `../ApiAgentService1` as an editable path dependency.

## Run

Start ApiAgentService1 on port 8001 first. Then run:

```sh
uv sync
uv run uvicorn consumer.app:app --port 8002 --reload
```

The upstream URL comes from `OPERATION_BASE_URL` (default `http://localhost:8001`).

## API

| Method | Path       | Body               | Response                                  |
|--------|------------|--------------------|-------------------------------------------|
| POST   | `/compute` | `{"a": 2, "b": 3}` | `{"result": 5.0, "source": "operation"}`  |
| GET    | `/health`  |                    | `{"status": "ok", "operation": "ok"}`     |

Errors: `422` for bad input, `502` if operation returns an error, and `503` if operation can't be reached.

```sh
curl -X POST localhost:8002/compute -H 'content-type: application/json' -d '{"a":2,"b":3}'
```

## Test

```sh
uv run pytest
```

The tests mock the upstream service with `httpx.MockTransport`, so ApiAgentService1 doesn't need to be running.

## Service2 impact agent

ApiAgentService1's change agent sends a `service1-changed` event whenever something is pushed to its `main` branch. That event starts [impact-agent.yml](.github/workflows/impact-agent.yml), which runs `agent/impact_agent.py`:

1. An LLM on NVIDIA NIM reads the message and the ApiAgentService1 diff, and works out how they affect this repo's code.
2. If this service is affected, the LLM suggests changes to `src/` and `tests/`. The agent applies them, runs the tests, and opens a PR on branch `agent/service1-<sha>`. If the tests fail, the PR is opened as a draft.
3. The agent emails an update covering the impact, the PR link, and the test results.

You can also start it by hand: go to the **Actions** tab, choose **Service2 impact agent**, then **Run workflow**, and enter a message and two ApiAgentService1 commits.

### Setup

Add these under **Settings → Secrets and variables → Actions**:

| Name | Type | Value |
|------|------|-------|
| `NVIDIA_API_KEY` | Secret | Your NVIDIA NIM API key |
| `EMAIL_TO` | Secret or variable | Recipient address. Separate several with commas. As a secret, the address is hidden in the public run logs. |
| `EMAIL_PROVIDER` | Variable or secret | `resend` (default) or `smtp` |
| `EMAIL_FROM` | Variable or secret | Optional sender. Default: `onboarding@resend.dev` for Resend, `SMTP_USERNAME` for SMTP |
| `RESEND_API_KEY` | Secret | Needed for `resend` |
| `SMTP_HOST`, `SMTP_PORT` | Variables or secrets | Needed for `smtp`, for example `smtp.gmail.com` and `587` |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Secrets | Needed for `smtp`. For Gmail, use an app password. |
| `NIM_MODEL` | Variable or secret | Optional. Default: `moonshotai/kimi-k3` |

Then turn on **Settings → Actions → General → Workflow permissions → Allow GitHub Actions to create and approve pull requests**.

Resend's test sender, `onboarding@resend.dev`, only delivers to the address you signed up to Resend with. To email other addresses, verify a domain in Resend.

PRs the agent opens don't start `tests.yml`, because GitHub doesn't trigger workflows from actions taken with `GITHUB_TOKEN`. The agent runs the tests itself and puts the results in the PR description instead.

### Try it locally

A dry run applies and tests the suggested changes, then reverts them. It doesn't open a PR or send email.

```sh
NVIDIA_API_KEY=... uv run agent/impact_agent.py --dry-run --message "..." --before <service1 sha> --after <service1 sha>
```

## Chat agent

`chat_agent/` holds a chat agent for this repo, built on agentkit (the ApiAgentKit repo). You talk to it in the ApiAgentUI app. It works in its own clones of both services under `~/.apiagent/service2/`. It can:
- read both codebases
- load an ApiAgentService1 change with `service1_change_context`, which reuses `agent/impact_agent.py`
- edit `src/` and `tests/`
- run the tests
- open pull requests
- email updates with `send_email`

Every email is saved and shown in the UI. You approve pull requests and emails before they happen.

```sh
cd chat_agent
cp .env.example .env   # add NVIDIA_API_KEY, GITHUB_TOKEN, EMAIL_TO, and email provider settings
uv sync
uv run pytest
```

To run it with the other agents, start from this repo's root:

```sh
uv run --project ../ApiAgentKit agentkit dev --registry ../ApiAgentUI/public/registry.json
```
