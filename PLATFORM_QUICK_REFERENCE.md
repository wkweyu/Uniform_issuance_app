# Platform Control Plane - Quick Reference

## Test Execution

```bash
# Run all tests (3 tests pass)
cd /home/frappe-user/uniform\ issuance\ app
source venv/bin/activate
SKIP_DB_ENV_CHECK=1 SQLALCHEMY_DATABASE_URI='sqlite:///:memory:' python3 -m pytest tests/ -v

# Run specific test file
SKIP_DB_ENV_CHECK=1 SQLALCHEMY_DATABASE_URI='sqlite:///:memory:' python3 -m pytest tests/test_onboarding.py -v

# Run with print output
SKIP_DB_ENV_CHECK=1 SQLALCHEMY_DATABASE_URI='sqlite:///:memory:' python3 -m pytest tests/ -v -s
```

## Start Application

```bash
# Development mode
cd /home/frappe-user/uniform\ issuance\ app
source venv/bin/activate
DB_HOST=dionysus.hostns.io \
DB_USER=u80655_schoolmngt \
DB_PASSWORD='Bernice@2026' \
DB_NAME=u80655_schoolmngt \
python3 app.py
# Visit: http://127.0.0.1:5000/platform/login
```

## Database Management

```bash
# Apply migrations to production DB
mysql -h dionysus.hostns.io -P 3306 -u u80655_schoolmngt -p u80655_schoolmngt < migrations/010_create_platform_tables.sql

# Check platform tables exist
mysql -h dionysus.hostns.io -P 3306 -u u80655_schoolmngt -p u80655_schoolmngt -e "USE u80655_schoolmngt; SHOW TABLES LIKE '%plan%'; SHOW TABLES LIKE '%subscription%';"
```

## Python Shell (API Testing)

```bash
source venv/bin/activate
export DB_HOST=dionysus.hostns.io
export DB_USER=u80655_schoolmngt
export DB_PASSWORD='Bernice@2026'
export DB_NAME=u80655_schoolmngt
python3

# Inside Python shell:
from app import create_app, db
app = create_app()

with app.app_context():
    from platform_bp.services.onboarding import onboard_school
    school, sub = onboard_school('Test School', 'TEST001', default_plan_name='Professional')
    print(f"Created school {school.id}: {school.name}")
    
    from platform_bp.models import Plan
    plans = Plan.query.all()
    print(f"Available plans: {[p.name for p in plans]}")
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Import error: `School` not found | Ensure `create_app()` completes before accessing platform models |
| Test DB connection error | Set `SKIP_DB_ENV_CHECK=1` and `SQLALCHEMY_DATABASE_URI='sqlite:///:memory:'` |
| Route 404 errors | Verify `/platform/*` routes exist via `app.url_map.iter_rules()` |
| Circular import on startup | Platform routes are deferred; they're only imported inside `init_platform()` |
| SMTP errors (email) | Set env vars: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (optional) |

## Key Files to Monitor

- `app.py` line 105-110: Platform blueprint initialization
- `platform_bp/__init__.py`: Blueprint definition and `init_platform()` function
- `platform_bp/models.py`: Platform data models
- `platform_bp/services/*.py`: Business logic (onboarding, subscriptions, audit)
- `migrations/010_create_platform_tables.sql`: Production schema
- `tests/conftest.py`: Test fixtures and setup

## Architecture Overview

```
Request → Flask App → Auth Check → Platform Route → Service Layer → Database
   ↑                                                      ↓
   └─────────────────── Audit Logging ────────────────︎↓
```

## Key Endpoints

| Method | Route | Purpose |
|--------|-------|---------|
| GET/POST | `/platform/login` | Platform staff login |
| POST | `/platform/logout` | Session termination |
| GET | `/platform/users` | List platform staff |
| POST | `/platform/users/create` | Create new staff |
| POST | `/platform/impersonate/start` | Impersonate school |
| POST | `/platform/impersonate/stop` | End impersonation |
| GET | `/platform/onboarding` | New school wizard |
| GET/POST | `/platform/schools` | School management |
| GET/POST | `/platform/subscriptions` | Subscription management |

## Production Readiness Checklist

- [x] All migrations applied
- [x] Database tables exist
- [x] Blueprint properly initialized
- [x] All 3 unit tests pass
- [x] Routes respond correctly
- [x] Audit logging functional
- [x] Service layer tested
- [x] No unhandled exceptions on startup
- [ ] SMTP credentials configured (optional)
- [ ] Rate limiting enabled (optional)
- [ ] Monitoring/alerting setup (optional)

---

_For detailed information, see `PLATFORM_IMPLEMENTATION_SUMMARY.md`_
