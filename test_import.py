#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/frappe-user/uniform issuance app')

try:
    print("Importing app...")
    from app import app
    print(f"✓ App imported successfully!")
    print(f"✓ App instance: {app}")
    print(f"✓ App debug mode: {app.debug}")
    print(f"✓ App routes count: {len(app.url_map._rules)}")
except Exception as e:
    print(f"✗ Error importing app: {e}")
    import traceback
    traceback.print_exc()
