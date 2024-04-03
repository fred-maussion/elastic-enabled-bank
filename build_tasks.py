import os
from django.core.management import execute_from_command_line
# Load Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
execute_from_command_line([])  # This loads the Django settings
from django.conf import settings
secret_key = settings.SECRET_KEY
with open('env.example', 'w') as f:
    f.write(f"DJANGO_SECRET_KEY={secret_key}\n")