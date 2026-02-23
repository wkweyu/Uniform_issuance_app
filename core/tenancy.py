from flask import session, g

def get_current_school_id():
    """Return the current tenant's school_id from the session."""
    return session.get("school_id")

def load_tenant_context():
    """Load the school context (tenant) for the current request."""
    g.school_id = get_current_school_id()
