"""Account-owned bookmarks, explicit rules and saved searches."""

from alembic import op

revision = "20260917_0014"
down_revision = "20260914_0013"
branch_labels = None
depends_on = None


def upgrade():
    from backend.app.db.schema import metadata

    for name in ("reading_state", "reading_rule", "reading_search", "reading_feed"):
        metadata.tables[name].create(bind=op.get_bind())


def downgrade():
    for name in ("reading_feed", "reading_search", "reading_rule", "reading_state"):
        op.drop_table(name)
