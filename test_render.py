from app import app
from flask import render_template
from datetime import datetime

with app.test_request_context():
    try:
        # Test if 'currency' filter is in jinja_env
        if 'currency' not in app.jinja_env.filters:
            print("FAILED: 'currency' filter not found in jinja_env.filters")
        else:
            print("SUCCESS: 'currency' filter found in jinja_env.filters")

        html = render_template('index.html',
                             total_students=10,
                             total_staff=5,
                             today_collections=100.50,
                             active_buses=2,
                             vouchers_today=1,
                             uniform_issued=20,
                             term_number=1,
                             year=2025,
                             total_classes=4)
        print("Index template rendered successfully")
    except Exception as e:
        print(f"Index template rendering failed: {e}")
        import traceback
        traceback.print_exc()
