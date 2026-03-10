"""create platform tables

Revision ID: 20260220_create_platform_tables
Revises: 
Create Date: 2026-02-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '20260220_create_platform_tables'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Plans
    op.create_table(
        'plans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('price_cents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('billing_period', sa.String(length=32), nullable=False, server_default='monthly'),
        sa.Column('features', mysql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        mysql_charset='utf8mb4'
    )
    op.create_index(op.f('ix_plans_name'), 'plans', ['name'], unique=True)

    # Subscriptions
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=True, server_default='active'),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('renewal_date', sa.DateTime(), nullable=True),
        sa.Column('billing_meta', mysql.JSON(), nullable=True),
        mysql_charset='utf8mb4'
    )
    op.create_index('ix_subscriptions_school_id', 'subscriptions', ['school_id'])
    op.create_index('ix_subscriptions_plan_id', 'subscriptions', ['plan_id'])

    # Platform users
    op.create_table(
        'platform_users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=64), nullable=False),
        sa.Column('assigned_school_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        mysql_charset='utf8mb4'
    )
    op.create_index(op.f('ix_platform_users_email'), 'platform_users', ['email'], unique=True)
    op.create_index('ix_platform_users_assigned_school_id', 'platform_users', ['assigned_school_id'])

    # Support tickets
    op.create_table(
        'support_tickets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('raised_by_email', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.String(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=True, server_default='open'),
        sa.Column('assigned_to_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')),
        mysql_charset='utf8mb4'
    )
    op.create_index('ix_support_tickets_school_id', 'support_tickets', ['school_id'])
    op.create_index('ix_support_tickets_assigned', 'support_tickets', ['assigned_to_user_id'])

    # Audit logs
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('actor_platform', sa.Boolean(), nullable=True, server_default='1'),
        sa.Column('action', sa.String(length=255), nullable=True),
        sa.Column('target_table', sa.String(length=255), nullable=True),
        sa.Column('target_id', sa.String(length=255), nullable=True),
        sa.Column('school_id', sa.Integer(), nullable=True),
        sa.Column('changes', mysql.JSON(), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        mysql_charset='utf8mb4'
    )
    op.create_index('ix_audit_logs_school_id', 'audit_logs', ['school_id'])


def downgrade():
    op.drop_index('ix_audit_logs_school_id', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index('ix_support_tickets_assigned', table_name='support_tickets')
    op.drop_index('ix_support_tickets_school_id', table_name='support_tickets')
    op.drop_table('support_tickets')
    op.drop_index('ix_platform_users_assigned_school_id', table_name='platform_users')
    op.drop_index(op.f('ix_platform_users_email'), table_name='platform_users')
    op.drop_table('platform_users')
    op.drop_index('ix_subscriptions_plan_id', table_name='subscriptions')
    op.drop_index('ix_subscriptions_school_id', table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index(op.f('ix_plans_name'), table_name='plans')
    op.drop_table('plans')
