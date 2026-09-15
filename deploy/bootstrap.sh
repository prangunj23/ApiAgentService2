#!/usr/bin/env bash
#
# Provision or update this service on an OCI VM: Oracle Linux 9 (OCI's default image) or
# Ubuntu 24.04, arm64 or amd64.
#
#   sudo ./bootstrap.sh              # clone/update, build, install units, leave stopped
#   sudo ./bootstrap.sh --start      # the same, then restart both services
#
# Idempotent: safe to re-run for every deploy. It never overwrites a filled-in
# /etc/apiagent/*.env, so your secrets survive an update.
set -euo pipefail

REPO_NAME="ApiAgentService2"
REPO_URL="https://github.com/prangunj23/ApiAgentService2.git"
BRANCH="main"
API_UNIT="consumer"
AGENT_UNIT="service2-agent"

APP_DIR="/opt/apiagent/$REPO_NAME"
STATE_DIR="/var/lib/apiagent"
CONFIG_DIR="/etc/apiagent"
# uv's own Python 3.13; Oracle Linux 9 ships 3.9. It lives under /opt rather than the
# service user's home in /var/lib because SELinux lets systemd run programs from /opt and
# denies them from /var/lib. The venvs link to this interpreter, so a copy under /var/lib
# would stop both services from starting.
PYTHON_DIR="/opt/apiagent/python"
SERVICE_USER="apiagent"
UV="/usr/local/bin/uv"

START=false
[[ "${1:-}" == "--start" ]] && START=true

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

# Commands below run as the service user, who can't read the invoking user's home.
cd /

say() { printf '\n== %s\n' "$*"; }
as_service() { sudo -u "$SERVICE_USER" "$@"; }
uv_as_service() { as_service env UV_CACHE_DIR="$STATE_DIR/uv-cache" UV_PYTHON_INSTALL_DIR="$PYTHON_DIR" "$UV" "$@"; }

say "Packages"
# git: the agent clones its repos. curl/ca-certificates/tar: the uv install and HTTPS to NIM and GitHub.
if command -v dnf >/dev/null; then
    dnf install -y -q git curl ca-certificates tar
elif command -v apt-get >/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq git curl ca-certificates tar
else
    echo "Unsupported OS: this script needs dnf or apt-get." >&2
    exit 1
fi

say "uv"
if [[ ! -x "$UV" ]]; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
fi
"$UV" --version

say "Service account and directories"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --home-dir "$STATE_DIR" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$STATE_DIR" "$STATE_DIR/uv-cache"
install -d -m 0750 "$CONFIG_DIR"
install -d -m 0755 /opt/apiagent
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0755 "$PYTHON_DIR"

say "Source at $APP_DIR"
# git runs as the service user, who owns the checkout. Run as root against a checkout owned
# by someone else, git refuses with "dubious ownership", which would break every re-deploy.
if [[ -d "$APP_DIR/.git" ]]; then
    as_service git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
    as_service git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
else
    install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0755 "$APP_DIR"
    as_service git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
echo "at $(as_service git -C "$APP_DIR" rev-parse --short HEAD)"

# --locked fails rather than silently resolving something the lockfile didn't pin.
# The chat agent installs agentkit from its vendored copy, so nothing else is needed on disk.
say "Building the API environment"
uv_as_service sync --locked --project "$APP_DIR"

say "Building the chat agent environment"
uv_as_service sync --locked --project "$APP_DIR/chat_agent"

say "Verifying the vendored agentkit"
as_service "$APP_DIR/chat_agent/.venv/bin/python" "$APP_DIR/chat_agent/vendor/check_vendor.py"

say "Configuration in $CONFIG_DIR"
for name in "$API_UNIT" "$AGENT_UNIT"; do
    target="$CONFIG_DIR/$name.env"
    if [[ -f "$target" ]]; then
        echo "kept    $target"
    else
        install -m 0600 "$APP_DIR/deploy/env/$name.env.example" "$target"
        echo "created $target  <-- fill this in"
    fi
done
if [[ -f "$CONFIG_DIR/registry.json" ]]; then
    echo "kept    $CONFIG_DIR/registry.json"
else
    install -m 0644 "$APP_DIR/deploy/registry.example.json" "$CONFIG_DIR/registry.json"
    echo "created $CONFIG_DIR/registry.json  <-- set the real hostnames"
fi
chown -R root:"$SERVICE_USER" "$CONFIG_DIR"
chmod 0640 "$CONFIG_DIR"/*.env

say "systemd units"
install -m 0644 "$APP_DIR/deploy/systemd/$API_UNIT.service" /etc/systemd/system/
install -m 0644 "$APP_DIR/deploy/systemd/$AGENT_UNIT.service" /etc/systemd/system/

if command -v restorecon >/dev/null; then
    say "SELinux labels"
    # Files created by clone, uv, and install inherit their parent directory's label.
    # Reset them to what the policy expects for their paths.
    restorecon -R /opt/apiagent "$CONFIG_DIR" \
        "/etc/systemd/system/$API_UNIT.service" "/etc/systemd/system/$AGENT_UNIT.service"
    echo "SELinux: $(getenforce 2>/dev/null || echo unknown)"
fi

systemctl daemon-reload
systemctl enable --quiet "$API_UNIT.service" "$AGENT_UNIT.service"

if $START; then
    say "Starting"
    systemctl restart "$API_UNIT.service" "$AGENT_UNIT.service"
    sleep 2
    systemctl --no-pager --lines=0 status "$API_UNIT.service" "$AGENT_UNIT.service" || true
else
    cat <<EOF

Installed but not started. Next:

  1. sudo nano $CONFIG_DIR/$AGENT_UNIT.env     # NVIDIA_API_KEY, GITHUB_TOKEN, AGENT_SHARED_TOKEN
  2. sudo nano $CONFIG_DIR/registry.json       # both agents' Tailscale URLs
  3. sudo $APP_DIR/deploy/set-tailscale-host.sh   # bind to the tailnet, open its firewall zone
  4. sudo systemctl start $API_UNIT $AGENT_UNIT

Re-run this script with --start for later deploys.
EOF
fi
