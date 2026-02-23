from flask import session, g
from sqlalchemy import event
from extensions import db

def get_current_school_id():
    """Return the current tenant's school_id from the session."""
    return session.get("school_id")

def load_tenant_context():
    """Load the school context (tenant) for the current request."""
    g.school_id = get_current_school_id()

def enable_multi_tenancy(app):
    """Enable automatic multi-tenancy enforcement for SQLAlchemy."""
    @event.listens_for(db.Session, "before_flush")
    def set_school_id(session, flush_context, instances):
        for obj in session.new:
            if hasattr(obj, 'school_id') and obj.school_id is None:
                if hasattr(g, 'school_id') and g.school_id:
                    obj.school_id = g.school_id
