"""add timestamps to positions

Revision ID: 45d73470761a
Revises: 
Create Date: 2025-09-29 16:53:24.348184

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '45d73470761a'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('positions', sa.Column('created_at', sa.String(), nullable=True))
    op.add_column('positions', sa.Column('updated_at', sa.String(), nullable=True))

    # Backfill values using SQLite datetime()
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE positions SET created_at = datetime('now','localtime') WHERE created_at IS NULL"))
    conn.execute(sa.text("UPDATE positions SET updated_at = datetime('now','localtime') WHERE updated_at IS NULL"))

def downgrade() -> None:
    """Downgrade schema."""
    pass
