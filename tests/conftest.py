"""Pytest configuration and fixtures for platform control plane tests."""
import pytest
import os
import sys

# CRITICAL: Set test DB URI and skip production env checks BEFORE any app imports
# This must happen at module load time before app.py is imported
os.environ['SKIP_DB_ENV_CHECK'] = '1'
os.environ['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
os.environ['FLASK_ENV'] = 'testing'

# Now safe to import app
from app import app as flask_app, db


@pytest.fixture(scope='session')
def app():
    """Create app instance configured for testing with SQLite."""
    app = flask_app
    app.config['TESTING'] = True
    # Explicitly override to ensure SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_ECHO'] = False
    app.config['LOGLEVEL'] = 'DEBUG'
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope='function')
def client(app):
    return app.test_client()


@pytest.fixture(scope='function')
def db_session(app):
    """Provide an isolated SQLite schema for each platform test."""
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield db.session
        db.session.remove()
        db.drop_all()
