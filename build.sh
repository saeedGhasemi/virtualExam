#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
npm ci
npm run build:css
python manage.py collectstatic --no-input
python manage.py migrate --no-input
