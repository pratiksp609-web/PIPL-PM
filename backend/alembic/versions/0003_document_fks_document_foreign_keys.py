"""document foreign keys

The documents table is created after the tables that reference it, so these
cyclic foreign keys are added in a separate step.

Revision ID: 0003_document_fks
Revises: 0002_seed_roles
Create Date: 2026-10-21 10:07:05.985756

"""
from typing import Sequence, Union

from alembic import op

revision: str = '0003_document_fks'
down_revision: Union[str, Sequence[str], None] = '0002_seed_roles'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FKS = [
    ("fk_client_purchase_orders_document", "client_purchase_orders", "document_id"),
    ("fk_documents_superseded_by", "documents", "superseded_by_id"),
    ("fk_quotation_versions_document", "quotation_versions", "document_id"),
    ("fk_supplier_purchase_orders_document", "supplier_purchase_orders", "document_id"),
]


def upgrade() -> None:
    for name, table, column in FKS:
        op.create_foreign_key(name, table, 'documents', [column], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    for name, table, _ in reversed(FKS):
        op.drop_constraint(name, table, type_='foreignkey')
