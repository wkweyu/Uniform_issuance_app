from functools import wraps
from flask import session, request, g
from core.db import get_db_connection
import json

def audit_log(action_name):
    """
    Decorator to log an action to the audit_log table.
    Expects an audit_log table to exist.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            result = f(*args, **kwargs)

            # Post-execution logging
            try:
                connection = get_db_connection()
                with connection.cursor() as cursor:
                    # Collect metadata
                    user_id = session.get('userNo', 0)
                    school_id = g.get('school_id', 0)
                    ip_address = request.remote_addr
                    details = {
                        'args': [str(a) for a in args],
                        'kwargs': {k: str(v) for k, v in kwargs.items()},
                        'url': request.url,
                        'method': request.method
                    }

                    # Try to log - if table doesn't exist, we skip
                    # (In a real scenario, we'd ensure the table exists)
                    cursor.execute("""
                        INSERT INTO audit_logs (user_id, school_id, action, details, ip_address, created_at)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                    """, (user_id, school_id, action_name, json.dumps(details), ip_address))
                connection.commit()
                connection.close()
            except Exception as e:
                # Fail silently to not break business logic if auditing fails
                pass

            return result
        return decorated_function
    return decorator
