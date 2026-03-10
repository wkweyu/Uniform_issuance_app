Platform package scaffold (renamed to avoid stdlib shadowing)

Overview
--------
This package provides a `platform_bp` Flask blueprint with models, routes, decorators and services for a SaaS control plane.

Quick registration
------------------
In `app.py` or your app factory call:

```py
from platform_bp import init_platform
init_platform(app, url_prefix='/platform')
```

Notes
-----
- `School` model is defined in `app.py` and reused here; do not duplicate that model.
- Models here use `db` from the main application to integrate with Flask-Migrate.
- This scaffold provides minimal route stubs; expand business logic in `platform_bp/services/`.
