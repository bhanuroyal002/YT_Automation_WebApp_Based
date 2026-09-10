#!/usr/bin/env bash
set -euo pipefail

# Run on a fresh Ubuntu EC2 host with sudo access.
# Usage: sudo DOMAIN=yts.example.com bash deploy/install_ec2.sh

DOMAIN="${DOMAIN:-yts.example.com}"
APP_DIR="/opt/yts-automation"
APP_USER="yts"
CONFIG_DIR="/etc/yts-automation"
REPO="https://github.com/bhanuroyal002/YT_Automation_WebApp_Based.git"

if [[ $EUID -ne 0 ]]; then
    echo "Run as root: sudo DOMAIN=$DOMAIN bash deploy/install_ec2.sh"
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx git adb

if ! id -u "$APP_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

mkdir -p "$APP_DIR" "$CONFIG_DIR"
if [[ ! -d "$APP_DIR/.git" ]]; then
    git clone "$REPO" "$APP_DIR"
else
    git -C "$APP_DIR" fetch origin
    git -C "$APP_DIR" reset --hard origin/main
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$CONFIG_DIR/yts-automation.env" ]]; then
    cp "$APP_DIR/deploy/yts-automation.env.example" "$CONFIG_DIR/yts-automation.env"
    sed -i "s#https://yts.example.com#https://$DOMAIN#g" "$CONFIG_DIR/yts-automation.env"
    SECRET="$("$APP_DIR/.venv/bin/python" - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
    sed -i "s#REPLACE_WITH_A_LONG_RANDOM_SECRET#$SECRET#" "$CONFIG_DIR/yts-automation.env"
fi
chown root:"$APP_USER" "$CONFIG_DIR/yts-automation.env"
chmod 640 "$CONFIG_DIR/yts-automation.env"

install -m 0644 "$APP_DIR/deploy/yts-automation.service" /etc/systemd/system/yts-automation.service
sed "s/server_name yts.example.com;/server_name $DOMAIN;/" \
    "$APP_DIR/deploy/nginx/yts-automation.conf" > /etc/nginx/sites-available/yts-automation.conf
ln -sfn /etc/nginx/sites-available/yts-automation.conf /etc/nginx/sites-enabled/yts-automation.conf
rm -f /etc/nginx/sites-enabled/default

mkdir -p "$APP_DIR/data"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/data"

nginx -t
systemctl daemon-reload
systemctl enable --now yts-automation
systemctl enable --now nginx

systemctl --no-pager --full status yts-automation || true
systemctl --no-pager --full status nginx || true

echo
echo "Application installed."
echo "HTTP endpoint: http://$DOMAIN"
echo "Next: create Route 53 DNS for $DOMAIN -> this EC2 Elastic IP, then enable HTTPS."
echo "IMPORTANT: EC2 must have network/VPN access to the DUT/ADB subnet before tests can run."
