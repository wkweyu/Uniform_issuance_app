# CSRF Protection Implementation Guide

## Overview
CSRF (Cross-Site Request Forgery) protection has been added to the Flask app using **Flask-WTF**.

## What Was Done

### 1. **Dependencies Updated**
- Added `Flask-WTF>=1.0` to `requirements.txt`

### 2. **Backend Configuration**
- Imported `CSRFProtect` from `flask_wtf.csrf`
- Initialized `csrf = CSRFProtect()` globally
- Initialized CSRF with app in `create_app()`: `csrf.init_app(app)`

### 3. **Protected Routes**
All routes are **automatically protected** except:
- `/login` (GET/POST) - Public route
- `/logout` (GET) - Public route
- JSON/API endpoints (exempted for AJAX calls):
  - `/submit_issuance` - JSON POST
  - `/cancel_receipt/<receipt_no>` - JSON POST
  - `/fleet/get_driver/<bus_id>` - JSON GET
  - `/fleet/fuel_invoices/<reg_no>/<from_date>/<to_date>` - JSON GET

## How to Add CSRF Tokens to Templates

### For HTML Forms (POST/PUT/DELETE)

Add the CSRF token hidden field inside all `<form>` tags:

```html
<form method="POST" action="/manage_prices">
    {{ csrf_token() }}
    <!-- Rest of form fields -->
    <input type="text" name="price_item_group">
    <button type="submit">Submit</button>
</form>
```

Or using Jinja2 shorthand:

```html
<form method="POST">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
    <!-- Form fields -->
</form>
```

### For AJAX Requests

Add CSRF token in request headers:

```javascript
// Get CSRF token from cookie or meta tag
const token = document.querySelector('meta[name="csrf-token"]').content;

// Or from hidden input
const token = document.querySelector('input[name="csrf_token"]').value;

// Use in fetch/AJAX
fetch('/submit_issuance', {
    method: 'POST',
    headers: {
        'X-CSRFToken': token,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({data})
});
```

### Add CSRF Meta Tag to Base Template

Add this to `base.html` in the `<head>` section:

```html
<head>
    <meta name="csrf-token" content="{{ csrf_token() }}">
    <!-- Other head content -->
</head>
```

## Templates to Update

The following templates contain forms and need CSRF tokens added:

1. **`issue_form.html`** - Issue uniform form
2. **`manage_prices.html`** - Price management form
3. **`student.html`** - Student admission form
4. **`record_service.html`** - Service record form
5. **`issue_fuel.html`** - Fuel voucher form
6. **`record_fuel_invoice.html`** - Fuel invoice form
7. **`edit_bus.html`** - Edit bus form
8. **`edit_invoice.html`** - Edit invoice form
9. **`edit_service.html`** - Edit service form
10. **`login.html`** - Login form (recommended)

## Error Handling

If a CSRF token is missing or invalid, the app will return:
- **400 Bad Request** with message "The CSRF token is missing."
- **403 Forbidden** with message "The CSRF token has expired."

To customize error handling, add error handler in `app.py`:

```python
from flask_wtf.csrf import CSRFError

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash(f"Security validation failed: {e.description}", "error")
    return redirect(request.referrer or url_for('index'))
```

## Installation

To install the new dependency:

```bash
pip install -r requirements.txt
```

Or directly:

```bash
pip install Flask-WTF>=1.0
```

## Testing CSRF Protection

1. **Test Protected Route**: Try submitting a form without CSRF token → Should fail with 400
2. **Test with Token**: Submit form with `csrf_token()` → Should succeed
3. **Test API Exempt Routes**: JSON endpoints work without tokens (exempted)

## Security Notes

✅ **What's Protected:**
- All form submissions (POST, PUT, DELETE)
- Session-based CSRF tokens
- Token rotates per session

❌ **What's Not Protected (By Design):**
- GET requests (safe by default)
- Public pages like `/login`, `/logout`
- JSON API endpoints (use HTTP headers for CSRF token)

## References

- [Flask-WTF Documentation](https://flask-wtf.readthedocs.io/)
- [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
