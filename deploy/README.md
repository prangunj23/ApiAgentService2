# Deploying ApiAgentService2 to OCI

This repo runs on one Oracle Always Free VM, by itself. It installs nothing from ApiAgentService1 — it calls that service over HTTP and keeps its own copy of the contract in `src/consumer/operation_client.py` — and nothing from the ApiAgentKit repo, since agentkit is vendored at `chat_agent/vendor/agentkit/`.

Two services run here:

| Unit | What | Port |
|---|---|---|
| `consumer.service` | the FastAPI API | 8002 |
| `service2-agent.service` | the agentkit chat agent | 9002 |

## Why Tailscale

Neither the API nor the agent has a login, and an OCI VM has a public IP. So nothing is published to the internet: both bind to the VM's Tailscale address, and the tailnet is the only way in. The UI on your laptop, and this VM's call out to the operation service on the other VM, all travel over the tailnet. You never open port 8002 or 9002 in an OCI security list, and never in the VM's own iptables.

`agentkit` adds a second layer on top: it rejects any request whose `Host` header isn't in `ALLOWED_HOSTS` (which stops DNS rebinding) and any cross-origin write from outside `UI_ORIGINS`.

## The VM

Create it as described in the main OCI walkthrough: **VM.Standard.A1.Flex**, 1 OCPU / 6 GB, Ubuntu 24.04, public subnet, your SSH key. That is half the Always Free A1 allowance; ApiAgentService1's VM takes the other half.

## First install

Deploy ApiAgentService1's VM first, so its API is there to point at. Then SSH in here:

```sh
# 1. Join the tailnet.
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname=apiagent-service2

# 2. Install the service. This clones the repo to /opt/apiagent, builds both
#    environments, and installs the systemd units without starting them.
git clone https://github.com/prangunj23/ApiAgentService2.git /tmp/bootstrap
sudo /tmp/bootstrap/deploy/bootstrap.sh

# 3. Fill in the secrets it created.
sudo nano /etc/apiagent/consumer.env             # OPERATION_BASE_URL -> the other VM
sudo nano /etc/apiagent/service2-agent.env       # NVIDIA_API_KEY, GITHUB_TOKEN, AGENT_SHARED_TOKEN, email
sudo nano /etc/apiagent/registry.json            # both agents' tailnet URLs

# 4. Bind to the tailnet instead of the public interface, and start.
sudo /opt/apiagent/ApiAgentService2/deploy/set-tailscale-host.sh
sudo systemctl start consumer service2-agent
```

`OPERATION_BASE_URL` is the one link between the two services. Point it at ApiAgentService1's **API** port on the tailnet — `http://apiagent-service1:8001` — not its agent port.

`AGENT_SHARED_TOKEN` must be the **same string on both VMs** — generate it once with `openssl rand -base64 32` — or the two agents answer each other with 401. `registry.json` must also be the same on both, listing each agent's tailnet URL.

## What goes where

| Path | Contents |
|---|---|
| `/opt/apiagent/ApiAgentService2/` | the checkout, owned by the `apiagent` user |
| `/etc/apiagent/*.env` | secrets and settings, mode 0640, root-owned, never overwritten by a re-run |
| `/etc/apiagent/registry.json` | the agent list both VMs share |
| `/var/lib/apiagent/service2/` | the agent's database, clones, research, memory |
| `/var/lib/apiagent/uv-cache/` | uv's cache |

The agent keeps its own clones under `/var/lib/apiagent` and never touches `/opt/apiagent`, so a deploy can't collide with work the agent is doing.

## Later deploys

```sh
sudo /opt/apiagent/ApiAgentService2/deploy/bootstrap.sh --start
```

It fetches `origin/main`, hard-resets to it, rebuilds with `uv sync --locked`, re-verifies the vendored agentkit, and restarts both units. Your `/etc/apiagent` files are left alone.

## Checking on it

```sh
systemctl status consumer service2-agent
journalctl -u service2-agent -f                  # follow the agent's log
curl "http://$(tailscale ip -4):8002/health"     # reports the upstream too
curl "http://$(tailscale ip -4):9002/health"     # agent
```

`/health` returns `{"status": "ok", "operation": "ok"}` when the other VM is reachable, and `"operation": "unreachable"` when it isn't — the quickest check that the cross-VM link works.

From your laptop, with the UI running, point its registry entry for `service2` at `http://apiagent-service2:9002`.

## When something is wrong

**`/health` says `"operation": "unreachable"`.** This VM can't reach ApiAgentService1. Check `OPERATION_BASE_URL` in `/etc/apiagent/consumer.env`, then `tailscale status`, then that the other VM's `BIND_HOST` is its tailnet address and not `127.0.0.1`.

**`/compute` returns 502.** The upstream answered with an error. Its contract may have moved away from `src/consumer/operation_client.py` — that file is this repo's copy of it, and the Service1 agent is meant to warn you before this happens.

**Agent returns 403 "Host not allowed".** The `Host` header isn't in `ALLOWED_HOSTS`. Re-run `set-tailscale-host.sh`, which writes both the MagicDNS name and the IP, and check what the caller actually uses.

**Agent returns 403 "Origin not allowed".** The UI's origin isn't in `UI_ORIGINS`. Add the exact scheme, host and port your dev server prints.

**Agent returns 401 on agent-to-agent calls.** `AGENT_SHARED_TOKEN` differs between the VMs, or is empty on one.

**`send_email` fails.** Check `EMAIL_PROVIDER` and its keys in `/etc/apiagent/service2-agent.env`. Resend's `onboarding@resend.dev` sender only delivers to the address you signed up with.

**`uv sync --locked` fails during a deploy.** The lockfile doesn't match `pyproject.toml`. Run `uv lock` locally, commit it, and deploy again — don't hand-edit the lockfile on the VM.
