#!/usr/bin/env bash
set -euo pipefail

APP_NAME="virtual-exam"
APP_USER="${APP_USER:-www-data}"
APP_PORT="${APP_PORT:-8013}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script with sudo on the server."
  exit 1
fi

apt-get update
apt-get install -y python3-venv python3-pip nginx nodejs npm postgresql-client

cd "$PROJECT_DIR"

if [[ ! -f .env ]]; then
  cp deploy/.env.production.example .env
  python3 - <<'PY'
from pathlib import Path
from secrets import token_urlsafe
p = Path(".env")
text = p.read_text()
text = text.replace("replace-with-a-long-random-secret", token_urlsafe(48))
p.write_text(text)
PY
  echo "Created .env. Edit database password before starting if PostgreSQL is not already configured."
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

npm install
npm run build:css

.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check --deploy || true

chown -R "$APP_USER:$APP_USER" "$PROJECT_DIR"

cat >/etc/systemd/system/${APP_NAME}.service <<EOF
[Unit]
Description=Virtual Exam Django application
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env
ExecStart=${PROJECT_DIR}/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:${APP_PORT} --workers 4 --threads 2 --timeout 120 --access-logfile - --error-logfile -
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/nginx/sites-available/${APP_NAME} <<EOF
server {
    listen 80;
    server_name 37.32.4.207;

    client_max_body_size 25M;

    location /static/ {
        alias ${PROJECT_DIR}/staticfiles/;
        access_log off;
        expires 30d;
    }

    location /media/ {
        alias ${PROJECT_DIR}/media/;
        expires 7d;
    }

    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 30s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/${APP_NAME} /etc/nginx/sites-enabled/${APP_NAME}
rm -f /etc/nginx/sites-enabled/default
nginx -t

systemctl daemon-reload
systemctl enable --now ${APP_NAME}
systemctl reload nginx

systemctl --no-pager --full status ${APP_NAME} || true
echo "Done. Open: http://37.32.4.207/"
