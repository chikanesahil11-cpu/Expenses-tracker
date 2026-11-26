#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

# Upgrade pip and install production dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# Collect static files into staticfiles/ via WhiteNoise
python manage.py collectstatic --no-input

# Apply database migrations
python manage.py migrate

# Optional: create initial superuser only if all DJANGO_SUPERUSER_* env vars are provided
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_EMAIL:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    python manage.py shell -c "
import os
from django.contrib.auth import get_user_model
User = get_user_model()
username = os.environ['DJANGO_SUPERUSER_USERNAME']
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(
        username=username,
        email=os.environ['DJANGO_SUPERUSER_EMAIL'],
        password=os.environ['DJANGO_SUPERUSER_PASSWORD'],
    )
    print(f'Superuser {username} created successfully')
"
fi

# Optional: seed initial demo data only when SEED_DEMO_USERNAME is explicitly configured
if [ -n "${SEED_DEMO_USERNAME:-}" ]; then
    python manage.py seed_demo_data --username "${SEED_DEMO_USERNAME}" || true
fi
