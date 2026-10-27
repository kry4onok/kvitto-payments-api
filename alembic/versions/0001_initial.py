"""Create tariffs and payments tables and seed the three fixed tariffs.

Revision ID: 0001_initial
Revises:
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    tariff_table = op.create_table(
        "tariffs",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_tariffs_price"),
    )
    op.bulk_insert(
        tariff_table,
        [
            {"id": "basic", "title": "Basic", "price": 990000},
            {"id": "standard", "title": "Standard", "price": 1990000},
            {"id": "premium", "title": "Premium", "price": 2990000},
        ],
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "tariff_id",
            sa.String(length=32),
            sa.ForeignKey("tariffs.id"),
            nullable=False,
        ),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("discount", sa.BigInteger(), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("installment_months", sa.Integer(), nullable=True),
        sa.Column("schedule", postgresql.JSONB(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("amount >= 0", name="ck_payments_amount"),
        sa.CheckConstraint("discount >= 0", name="ck_payments_discount"),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'refunded')",
            name="ck_payments_status",
        ),
        sa.CheckConstraint(
            "method IN ('card', 'sbp', 'installment')", name="ck_payments_method"
        ),
    )
    op.create_index("ix_payments_email", "payments", ["email"])


def downgrade() -> None:
    op.drop_index("ix_payments_email", table_name="payments")
    op.drop_table("payments")
    op.drop_table("tariffs")
