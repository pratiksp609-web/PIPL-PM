"""seed roles

Revision ID: 0002_seed_roles
Revises: 651f1917e01b
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_seed_roles"
down_revision = "651f1917e01b"
branch_labels = None
depends_on = None

ROLES = [
    ("admin", "Full access including users, settings and all financial data"),
    ("project_manager", "Manage projects, clients, commercial documents and payments"),
    ("team_member", "Work on assigned projects: tasks, updates and non-financial documents"),
]


def upgrade():
    roles = sa.table("roles", sa.column("name", sa.String), sa.column("description", sa.String))
    op.bulk_insert(roles, [{"name": n, "description": d} for n, d in ROLES])


def downgrade():
    op.execute("DELETE FROM roles WHERE name IN ('admin', 'project_manager', 'team_member')")
