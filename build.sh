#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

# Upgrade pip and install production dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# Collect static files into staticfiles/ via WhiteNoise
python manage.py collectstatic --no-input

# Apply database migrations to PostgreSQL
python manage.py migrate
