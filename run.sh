#!/bin/bash
set -euo pipefail

cd "/home/frappe-user/uniform issuance app"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5013}"

export HOST PORT

exec ./venv/bin/python - <<'PY'
import os
from app import app

host = os.environ.get('HOST', '127.0.0.1')
port = int(os.environ.get('PORT', '5013'))

app.run(host=host, port=port, debug=False)
PY
