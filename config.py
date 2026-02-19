import os
from pathlib import Path

# Load .env file if present (for local development). Production should set real env vars.
try:
	from dotenv import load_dotenv
	env_path = Path(__file__).parent / '.env'
	if env_path.exists():
		load_dotenv(env_path)
except Exception:
	# If python-dotenv isn't available, environment variables still work.
	pass

# Configuration values are sourced from environment variables.
# Defaults are intentionally empty or localhost to avoid committing secrets.
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_USER = os.environ.get('DB_USER', '')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_NAME = os.environ.get('DB_NAME', '')
DB_PORT = int(os.environ.get('DB_PORT', 3306))
