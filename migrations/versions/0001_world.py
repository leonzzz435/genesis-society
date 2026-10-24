"""Initial world and request ledger; framework checkpoint tables are framework-owned."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "society_world",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("data", sa.JSON, nullable=False),
    )
    op.create_table(
        "society_request",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("actor", sa.String, nullable=False),
        sa.Column("phase", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
    )
    op.create_index("ix_society_request_actor", "society_request", ["actor"])
    op.create_index("ix_society_request_phase", "society_request", ["phase"])


def downgrade():
    raise RuntimeError("Destructive downgrade is deliberately not automated")
