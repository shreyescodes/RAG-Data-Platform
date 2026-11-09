#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu 24.04 VM (e.g. Oracle Cloud Always Free
# Ampere A1). Run as a sudo-capable user:
#   curl -fsSLO https://raw.githubusercontent.com/shreyescodes/RAG-Data-Platform/main/deploy/server-setup.sh
#   less server-setup.sh && sudo bash server-setup.sh <deploy-user>
#
# Installs Docker, opens ports 80/443 in the host firewall, creates /opt/rag
# owned by the deploy user, and schedules the nightly backup.
set -euo pipefail

deploy_user=${1:?usage: server-setup.sh <deploy-user>}
app_dir=/opt/rag

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }

# --- Docker Engine + compose plugin (official apt repository) ---------------------
if ! command -v docker >/dev/null; then
    apt-get update
    apt-get install -y ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

# Docker keeps its own logs small (the compose files also rotate per service).
if [ ! -f /etc/docker/daemon.json ]; then
    echo '{"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}}' > /etc/docker/daemon.json
    systemctl restart docker
fi

# --- Deploy user and app directory -------------------------------------------------
id "$deploy_user" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$deploy_user"
usermod -aG docker "$deploy_user"
install -d -o "$deploy_user" -g "$deploy_user" -m 750 "$app_dir"
install -d -o "$deploy_user" -g "$deploy_user" -m 700 "$app_dir/backups"

# --- Host firewall -------------------------------------------------------------------
# Oracle's Ubuntu images ship iptables rules that reject everything except SSH,
# even when the cloud Security List allows it. Open HTTP/HTTPS (and HTTP/3) before
# the reject rule, and persist the change.
if command -v netfilter-persistent >/dev/null; then
    for rule in "-p tcp --dport 80" "-p tcp --dport 443" "-p udp --dport 443"; do
        # shellcheck disable=SC2086
        iptables -C INPUT $rule -j ACCEPT 2>/dev/null || iptables -I INPUT 1 $rule -j ACCEPT
    done
    netfilter-persistent save
fi

# --- Nightly backup at 03:00 UTC -------------------------------------------------------
cron_line="0 3 * * * cd $app_dir && ./deploy/backup.sh >> $app_dir/backups/backup.log 2>&1"
( crontab -u "$deploy_user" -l 2>/dev/null | grep -v 'deploy/backup.sh' || true; echo "$cron_line" ) \
    | crontab -u "$deploy_user" -

# Security updates install themselves (Ubuntu default; make sure it is on).
apt-get install -y unattended-upgrades >/dev/null

echo "Done. Next: put .env in $app_dir (see docs/deployment.md), then run the Deploy workflow."
