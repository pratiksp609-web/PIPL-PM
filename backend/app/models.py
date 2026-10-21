"""Relational data model. Every project-scoped record links back to projects.id."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

Money = Numeric(14, 2)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuthorMixin(TimestampMixin):
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


# ---------------------------------------------------------------- users & auth
class Role(Base):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(ForeignKey("roles.name"), default="team_member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # JWT jti
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))


class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_interval_minutes: Mapped[int] = mapped_column(Integer, default=120)
    work_start: Mapped[dt.time] = mapped_column(Time, default=dt.time(9, 0))
    work_end: Mapped[dt.time] = mapped_column(Time, default=dt.time(18, 0))
    work_days: Mapped[str] = mapped_column(String(32), default="0,1,2,3,4,5")  # Monday=0
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled_notification_types: Mapped[list] = mapped_column(JSON, default=list)
    last_progress_reminder_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("reminder_interval_minutes BETWEEN 15 AND 1440", name="ck_reminder_interval"),
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ---------------------------------------------------------------- clients & projects
class Client(AuthorMixin, Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    company_name: Mapped[str] = mapped_column(String(200), index=True)
    contact_person: Mapped[str | None] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    billing_address: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(String(15))
    notes: Mapped[str | None] = mapped_column(Text)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    projects: Mapped[list[Project]] = relationship(back_populates="client")
    __table_args__ = (
        Index("uq_clients_gstin", "gstin", unique=True, postgresql_where=text("gstin IS NOT NULL")),
        Index("uq_clients_company_lower", func.lower(company_name), unique=True),
    )


class Project(AuthorMixin, Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    expected_completion_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    actual_completion_date: Mapped[dt.date | None] = mapped_column(Date)
    budget: Mapped[Decimal | None] = mapped_column(Money)
    contract_value: Mapped[Decimal | None] = mapped_column(Money)  # manually approved commercial value
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(20), default="planning", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    client: Mapped[Client] = relationship(back_populates="projects")
    manager: Mapped[User | None] = relationship(foreign_keys=[manager_id])
    members: Mapped[list[ProjectMember]] = relationship(cascade="all, delete-orphan")
    __table_args__ = (
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_project_progress"),
        CheckConstraint(
            "expected_completion_date IS NULL OR start_date IS NULL OR expected_completion_date >= start_date",
            name="ck_project_dates",
        ),
        CheckConstraint("budget IS NULL OR budget >= 0", name="ck_project_budget"),
        CheckConstraint("contract_value IS NULL OR contract_value >= 0", name="ck_project_contract"),
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


# ---------------------------------------------------------------- documents
class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(80), unique=True)
    mime_type: Mapped[str] = mapped_column(String(128))
    extension: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    quotation_version_id: Mapped[int | None] = mapped_column(ForeignKey("quotation_versions.id", ondelete="SET NULL"))
    client_po_id: Mapped[int | None] = mapped_column(ForeignKey("client_purchase_orders.id", ondelete="SET NULL"))
    supplier_po_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_purchase_orders.id", ondelete="SET NULL"))
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments_received.id", ondelete="SET NULL"))
    supplier_payment_id: Mapped[int | None] = mapped_column(ForeignKey("supplier_payments.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    update_id: Mapped[int | None] = mapped_column(ForeignKey("project_updates.id", ondelete="SET NULL"))
    report_id: Mapped[int | None] = mapped_column(ForeignKey("generated_reports.id", ondelete="SET NULL"))
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL", use_alter=True))
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship()
    uploaded_by: Mapped[User | None] = relationship(foreign_keys=[uploaded_by_id])


# ---------------------------------------------------------------- quotations
class Quotation(AuthorMixin, Base):
    __tablename__ = "quotations"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), index=True)
    quotation_number: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(String(255))

    versions: Mapped[list[QuotationVersion]] = relationship(
        back_populates="quotation", order_by="QuotationVersion.revision_number", cascade="all, delete-orphan"
    )
    __table_args__ = (UniqueConstraint("client_id", "quotation_number", name="uq_quotation_client_number"),)


class QuotationVersion(AuthorMixin, Base):
    __tablename__ = "quotation_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("quotations.id", ondelete="CASCADE"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer, default=0)
    quotation_date: Mapped[dt.date | None] = mapped_column(Date)
    validity_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    tax_amount: Mapped[Decimal | None] = mapped_column(Money)
    total_amount: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    payment_terms: Mapped[str | None] = mapped_column(Text)
    delivery_terms: Mapped[str | None] = mapped_column(Text)
    delivery_date: Mapped[dt.date | None] = mapped_column(Date)
    scope: Mapped[str | None] = mapped_column(Text)
    line_items: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL", use_alter=True))
    extraction: Mapped[dict | None] = mapped_column(JSON)  # {field: {value, confidence, source}}
    extraction_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    quotation: Mapped[Quotation] = relationship(back_populates="versions")
    document: Mapped[Document | None] = relationship(foreign_keys=[document_id])
    __table_args__ = (
        UniqueConstraint("quotation_id", "revision_number", name="uq_quotation_revision"),
        CheckConstraint("total_amount IS NULL OR total_amount >= 0", name="ck_qv_total"),
        CheckConstraint("subtotal IS NULL OR subtotal >= 0", name="ck_qv_subtotal"),
        CheckConstraint("tax_amount IS NULL OR tax_amount >= 0", name="ck_qv_tax"),
    )


# ---------------------------------------------------------------- client POs
class ClientPurchaseOrder(AuthorMixin, Base):
    __tablename__ = "client_purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), index=True)
    po_number: Mapped[str] = mapped_column(String(64), index=True)
    issue_date: Mapped[dt.date | None] = mapped_column(Date)
    po_value: Mapped[Decimal | None] = mapped_column(Money)
    tax_amount: Mapped[Decimal | None] = mapped_column(Money)
    total_value: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    delivery_terms: Mapped[str | None] = mapped_column(Text)
    payment_terms: Mapped[str | None] = mapped_column(Text)
    delivery_date: Mapped[dt.date | None] = mapped_column(Date)
    scope: Mapped[str | None] = mapped_column(Text)
    line_items: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="received", index=True)
    quotation_version_id: Mapped[int | None] = mapped_column(ForeignKey("quotation_versions.id", ondelete="SET NULL"))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL", use_alter=True))
    extraction: Mapped[dict | None] = mapped_column(JSON)
    extraction_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)

    document: Mapped[Document | None] = relationship(foreign_keys=[document_id])
    __table_args__ = (
        UniqueConstraint("client_id", "po_number", name="uq_client_po_number"),
        CheckConstraint("total_value IS NULL OR total_value >= 0", name="ck_cpo_total"),
        CheckConstraint("po_value IS NULL OR po_value >= 0", name="ck_cpo_value"),
        CheckConstraint("tax_amount IS NULL OR tax_amount >= 0", name="ck_cpo_tax"),
    )


# ---------------------------------------------------------------- client payments (receivables)
class PaymentReceived(AuthorMixin, Base):
    __tablename__ = "payments_received"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), index=True)
    client_po_id: Mapped[int | None] = mapped_column(ForeignKey("client_purchase_orders.id", ondelete="SET NULL"))
    amount: Mapped[Decimal] = mapped_column(Money)
    payment_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    due_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    payment_type: Mapped[str] = mapped_column(String(16), default="partial")
    milestone_label: Mapped[str | None] = mapped_column(String(128))
    method: Mapped[str | None] = mapped_column(String(20))
    transaction_reference: Mapped[str | None] = mapped_column(String(100))
    bank_reference: Mapped[str | None] = mapped_column(String(100))
    invoice_reference: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="recorded", index=True)
    verified_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        Index(
            "uq_payment_txn_ref",
            func.lower(transaction_reference),
            unique=True,
            postgresql_where=text("transaction_reference IS NOT NULL"),
        ),
    )


# ---------------------------------------------------------------- procurement (supplier side)
class Supplier(AuthorMixin, Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    contact_person: Mapped[str | None] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(Text)
    gstin: Mapped[str | None] = mapped_column(String(15))
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("uq_suppliers_name_lower", func.lower(name), unique=True),)


class BOMItem(AuthorMixin, Base):
    __tablename__ = "bom_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    item_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    specification: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(16), default="nos")
    estimated_rate: Mapped[Decimal | None] = mapped_column(Money)
    actual_rate: Mapped[Decimal | None] = mapped_column(Money)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    required_date: Mapped[dt.date | None] = mapped_column(Date)
    procurement_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    remarks: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    supplier: Mapped[Supplier | None] = relationship()
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_bom_qty"),
        CheckConstraint("received_quantity >= 0", name="ck_bom_received"),
        CheckConstraint("estimated_rate IS NULL OR estimated_rate >= 0", name="ck_bom_est"),
        CheckConstraint("actual_rate IS NULL OR actual_rate >= 0", name="ck_bom_act"),
    )


class SupplierPurchaseOrder(AuthorMixin, Base):
    __tablename__ = "supplier_purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True)
    po_number: Mapped[str] = mapped_column(String(64), index=True)
    po_date: Mapped[dt.date | None] = mapped_column(Date)
    delivery_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    actual_delivery_date: Mapped[dt.date | None] = mapped_column(Date)
    subtotal: Mapped[Decimal] = mapped_column(Money, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Money, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Money, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    payment_terms: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="ordered", index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL", use_alter=True))
    notes: Mapped[str | None] = mapped_column(Text)

    supplier: Mapped[Supplier] = relationship()
    items: Mapped[list[SupplierPOItem]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan", order_by="SupplierPOItem.id"
    )
    __table_args__ = (UniqueConstraint("supplier_id", "po_number", name="uq_supplier_po_number"),)


class SupplierPOItem(Base):
    __tablename__ = "supplier_po_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_po_id: Mapped[int] = mapped_column(ForeignKey("supplier_purchase_orders.id", ondelete="CASCADE"), index=True)
    bom_item_id: Mapped[int | None] = mapped_column(ForeignKey("bom_items.id", ondelete="SET NULL"), index=True)
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit: Mapped[str] = mapped_column(String(16), default="nos")
    unit_price: Mapped[Decimal] = mapped_column(Money)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    amount: Mapped[Decimal] = mapped_column(Money)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)

    purchase_order: Mapped[SupplierPurchaseOrder] = relationship(back_populates="items")
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_spoi_qty"),
        CheckConstraint("unit_price >= 0", name="ck_spoi_price"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_spoi_tax"),
        CheckConstraint("received_quantity >= 0", name="ck_spoi_received"),
    )


class SupplierPayment(AuthorMixin, Base):
    """Money paid OUT to suppliers. Never mixed with client receivables."""

    __tablename__ = "supplier_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_po_id: Mapped[int] = mapped_column(ForeignKey("supplier_purchase_orders.id", ondelete="RESTRICT"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    payment_date: Mapped[dt.date] = mapped_column(Date)
    method: Mapped[str | None] = mapped_column(String(20))
    reference: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(12), default="recorded")
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_supplier_payment_amount"),
        Index("uq_supplier_payment_ref", func.lower(reference), unique=True, postgresql_where=text("reference IS NOT NULL")),
    )


# ---------------------------------------------------------------- work tracking
class Task(AuthorMixin, Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="todo", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    due_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project | None] = relationship()
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    __table_args__ = (CheckConstraint("progress BETWEEN 0 AND 100", name="ck_task_progress"),)


class ProjectUpdate(Base):
    __tablename__ = "project_updates"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    update_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    health: Mapped[str] = mapped_column(String(12), default="on_track")
    work_completed: Mapped[str] = mapped_column(Text)
    progress: Mapped[int] = mapped_column(Integer)
    work_in_progress: Mapped[str | None] = mapped_column(Text)
    blockers: Mapped[str | None] = mapped_column(Text)
    risks: Mapped[str | None] = mapped_column(Text)
    materials_required: Mapped[str | None] = mapped_column(Text)
    next_steps: Mapped[str | None] = mapped_column(Text)
    planned_completion_date: Mapped[dt.date | None] = mapped_column(Date)
    remarks: Mapped[str | None] = mapped_column(Text)
    revision_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    edited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    project: Mapped[Project] = relationship()
    author: Mapped[User | None] = relationship(foreign_keys=[author_id])
    __table_args__ = (CheckConstraint("progress BETWEEN 0 AND 100", name="ck_update_progress"),)


class ProjectUpdateRevision(Base):
    __tablename__ = "project_update_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    update_id: Mapped[int] = mapped_column(ForeignKey("project_updates.id", ondelete="CASCADE"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)  # content before the edit
    reason: Mapped[str | None] = mapped_column(String(255))
    edited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    edited_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CalendarEvent(AuthorMixin, Base):
    __tablename__ = "calendar_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(16), default="meeting")  # meeting | reminder | milestone | other
    start_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    location: Mapped[str | None] = mapped_column(String(255))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    remind_minutes_before: Mapped[int | None] = mapped_column(Integer)
    reminder_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("end_at IS NULL OR end_at >= start_at", name="ck_event_range"),)


# ---------------------------------------------------------------- notifications, audit, reports
class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(255))
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    dedupe_key: Mapped[str] = mapped_column(String(160))
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str] = mapped_column(String(16), default="not_requested")  # not_requested|not_configured|sent|failed
    email_error: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key", name="uq_notification_dedupe"),)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True)
    changes: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped[User | None] = relationship()
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)


class GeneratedReport(Base):
    __tablename__ = "generated_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    period_type: Mapped[str] = mapped_column(String(12))  # weekly|monthly|quarterly|annual|custom
    scope: Mapped[str] = mapped_column(String(10))  # company|project
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    period_start: Mapped[dt.date] = mapped_column(Date)
    period_end: Mapped[dt.date] = mapped_column(Date)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    data: Mapped[dict] = mapped_column(JSON)
    ai_status: Mapped[str] = mapped_column(String(16), default="not_configured")  # not_configured|success|failed|skipped
    ai_analysis: Mapped[dict | None] = mapped_column(JSON)
    ai_error: Mapped[str | None] = mapped_column(String(500))
    generated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), default="running")
    details: Mapped[dict | None] = mapped_column(JSON)
