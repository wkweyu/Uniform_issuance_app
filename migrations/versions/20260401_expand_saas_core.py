"""expand saas core

Revision ID: 20260401_expand_saas_core
Revises: 20260220_create_platform_tables
Create Date: 2026-04-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260401_expand_saas_core'
down_revision = '20260220_create_platform_tables'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('schools', sa.Column('email', sa.String(length=255), nullable=True))
    op.add_column('schools', sa.Column('phone', sa.String(length=64), nullable=True))
    op.add_column('schools', sa.Column('address', sa.String(length=255), nullable=True))
    op.add_column('schools', sa.Column('city', sa.String(length=128), nullable=True))
    op.add_column('schools', sa.Column('country', sa.String(length=128), nullable=True))
    op.add_column('schools', sa.Column('logo', sa.String(length=255), nullable=True))
    op.add_column('schools', sa.Column('subscription_plan', sa.String(length=64), nullable=True))
    op.add_column('schools', sa.Column('subscription_status', sa.String(length=32), nullable=False, server_default='trial'))
    op.add_column('schools', sa.Column('subscription_start', sa.Date(), nullable=True))

    op.create_table(
        'school_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('school_name', sa.String(length=255), nullable=True),
        sa.Column('logo', sa.String(length=255), nullable=True),
        sa.Column('address', sa.String(length=255), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=64), nullable=True),
        sa.Column('website', sa.String(length=255), nullable=True),
        sa.Column('timezone', sa.String(length=64), nullable=False, server_default='UTC'),
        sa.Column('currency', sa.String(length=16), nullable=False, server_default='USD'),
        sa.Column('grading_system', sa.String(length=64), nullable=True),
        sa.Column('report_template', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('school_id', name='uq_school_settings_school_id'),
        mysql_charset='utf8mb4'
    )
    op.create_index('ix_school_settings_school_id', 'school_settings', ['school_id'])

    op.add_column('subscriptions', sa.Column('billing_cycle', sa.String(length=32), nullable=False, server_default='monthly'))
    op.add_column('subscriptions', sa.Column('amount_cents', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('subscriptions', sa.Column('payment_reference', sa.String(length=128), nullable=True))
    op.add_column('subscriptions', sa.Column('trial_ends_at', sa.DateTime(), nullable=True))
    op.add_column('subscriptions', sa.Column('grace_period_ends_at', sa.DateTime(), nullable=True))
    op.add_column('subscriptions', sa.Column('ended_at', sa.DateTime(), nullable=True))
    op.add_column('subscriptions', sa.Column('archived_at', sa.DateTime(), nullable=True))

    op.add_column('platform_users', sa.Column('name', sa.String(length=255), nullable=True))
    op.add_column('platform_users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')))
    op.add_column('platform_users', sa.Column('portfolio_scope', sa.JSON(), nullable=True))
    op.add_column('platform_users', sa.Column('mfa_enabled', sa.Boolean(), nullable=False, server_default=sa.text('0')))


def downgrade():
    op.drop_column('platform_users', 'mfa_enabled')
    op.drop_column('platform_users', 'portfolio_scope')
    op.drop_column('platform_users', 'is_active')
    op.drop_column('platform_users', 'name')

    op.drop_column('subscriptions', 'archived_at')
    op.drop_column('subscriptions', 'ended_at')
    op.drop_column('subscriptions', 'grace_period_ends_at')
    op.drop_column('subscriptions', 'trial_ends_at')
    op.drop_column('subscriptions', 'payment_reference')
    op.drop_column('subscriptions', 'amount_cents')
    op.drop_column('subscriptions', 'billing_cycle')

    op.drop_index('ix_school_settings_school_id', table_name='school_settings')
    op.drop_table('school_settings')

    op.drop_column('schools', 'subscription_start')
    op.drop_column('schools', 'subscription_status')
    op.drop_column('schools', 'subscription_plan')
    op.drop_column('schools', 'logo')
    op.drop_column('schools', 'country')
    op.drop_column('schools', 'city')
    op.drop_column('schools', 'address')
    op.drop_column('schools', 'phone')
    op.drop_column('schools', 'email')