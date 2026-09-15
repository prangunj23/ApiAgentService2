#!/usr/bin/env bash
#
# Point this VM's services at its Tailscale address instead of the public interface.
#
#   sudo ./set-tailscale-host.sh
#
# The agent has no login and this VM has a public IP, so binding the tailnet address is
# what keeps the agent off the internet. Run it after `tailscale up`, and again if the
# tailnet address ever changes. Re-running is safe.
set -euo pipefail

CONFIG_DIR="/etc/apiagent"
API_ENV="$CONFIG_DIR/consumer.env"
AGENT_ENV="$CONFIG_DIR/service2-agent.env"

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
command -v tailscale >/dev/null || { echo "tailscale is not installed. See deploy/README.md." >&2; exit 1; }

IP="$(tailscale ip -4 2>/dev/null | head -n1)"
[[ -n "$IP" ]] || { echo "No Tailscale IPv4 address yet. Run 'sudo tailscale up' first." >&2; exit 1; }

# MagicDNS short name, e.g. apiagent-service2. This is the Host header the UI and the
# other agent will send, so it has to be in ALLOWED_HOSTS or the agent answers 403.
NAME="$(tailscale status --json 2>/dev/null | grep -o '"DNSName":"[^"]*"' | head -n1 | cut -d'"' -f4 | cut -d. -f1)"
NAME="${NAME:-$(hostname -s)}"

# Replace KEY=... in place, or append it if the key is absent.
set_key() {
    local file="$1" key="$2" value="$3"
    if grep -q "^$key=" "$file"; then
        sed -i "s|^$key=.*|$key=$value|" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >>"$file"
    fi
    echo "  $key=$value"
}

AGENT_PORT="$(grep -E '^AGENT_PORT=' "$AGENT_ENV" | cut -d= -f2 | tr -d ' ')"
AGENT_PORT="${AGENT_PORT:-9002}"

echo "Tailscale address $IP ($NAME)"
echo "$API_ENV:"
set_key "$API_ENV" BIND_HOST "$IP"
echo "$AGENT_ENV:"
set_key "$AGENT_ENV" AGENT_HOST "$IP"
set_key "$AGENT_ENV" ALLOWED_HOSTS "$NAME:$AGENT_PORT,$IP:$AGENT_PORT"

echo
echo "Restarting."
systemctl restart consumer.service service2-agent.service 2>/dev/null || {
    echo "Services not running yet; start them when the rest of the config is filled in."
}
