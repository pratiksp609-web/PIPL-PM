"""Request and response schemas. All input is validated here before touching the database."""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator, model_validator

Str = Annotated[str, StringConstraints(strip_whitespace=True)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)]
NonNegMoney = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
PosMoney = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
Currency = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{3}$")]
Percent = Annotated[int, Field(ge=0, le=100)]

ProjectStatus = Literal["planning", "active", "on_hold", "completed", "cancelled"]
Priority = Literal["low", "medium", "high", "critical"]
QuotationStatus = Literal["draft", "submitted", "approved", "rejected", "expired", "superseded"]
ClientPOStatus = Literal["received", "under_review", "verified", "rejected", "cancelled"]
PaymentStatus = Literal["recorded", "pending", "failed", "reversed", "verified"]
PaymentType = Literal["advance", "milestone", "partial", "final", "other"]
PaymentMethod = Literal["bank_transfer", "cheque", "upi", "cash", "card", "other"]
ProcurementStatus = Literal["pending", "rfq", "ordered", "partially_received", "received", "cancelled", "delayed"]
SupplierPOStatus = Literal["draft", "ordered", "partially_received", "received", "cancelled", "delayed"]
SupplierPaymentStatus = Literal["recorded", "verified", "reversed"]
TaskStatus = Literal["todo", "in_progress", "blocked", "under_review", "completed"]
Health = Literal["on_track", "at_risk", "delayed", "blocked"]
EventType = Literal["meeting", "reminder", "milestone", "other"]
Role = Literal["admin", "project_manager", "team_member"]

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def _empty_to_none(v):
    if isinstance(v, str) and not v.strip():
        return None
    return v


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _blank_strings(cls, data):
        if isinstance(data, dict):
            return {k: _empty_to_none(v) for k, v in data.items()}
        return data


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth & users
class LoginIn(Base):
    identifier: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class UserOut(Out):
    id: int
    email: str
    username: str
    full_name: str
    role: str
    is_active: bool
    last_login_at: dt.datetime | None = None


class UserCreate(Base):
    email: EmailStr
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")]
    full_name: Name
    role: Role = "team_member"
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]


class UserUpdate(Base):
    full_name: Name | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)] | None = None


class PasswordChange(Base):
    current_password: str
    new_password: Annotated[str, StringConstraints(min_length=8, max_length=128)]


# ---------------------------------------------------------------- clients
class ClientIn(Base):
    name: Name
    company_name: Name
    contact_person: Short | None = None
    email: EmailStr | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9+()\-\s]{6,20}$")] | None = None
    billing_address: Text | None = None
    gstin: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True)] | None = None
    notes: Text | None = None

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v):
        if v and not GSTIN_RE.match(v):
            raise ValueError("GSTIN must be a valid 15-character GST number (e.g. 27ABCDE1234F1Z5)")
        return v


class ClientUpdate(ClientIn):
    name: Name | None = None
    company_name: Name | None = None


class ClientOut(Out):
    id: int
    name: str
    company_name: str
    contact_person: str | None
    email: str | None
    phone: str | None
    billing_address: str | None
    gstin: str | None
    notes: str | None
    is_sample: bool
    archived_at: dt.datetime | None
    created_at: dt.datetime
    project_count: int | None = None


# ---------------------------------------------------------------- projects
class ProjectIn(Base):
    name: Name
    client_id: int
    description: Text | None = None
    manager_id: int | None = None
    start_date: dt.date | None = None
    expected_completion_date: dt.date | None = None
    actual_completion_date: dt.date | None = None
    budget: NonNegMoney | None = None
    contract_value: NonNegMoney | None = None
    currency: Currency = "INR"
    status: ProjectStatus = "planning"
    progress: Percent = 0
    priority: Priority = "medium"
    member_ids: list[int] = []

    @model_validator(mode="after")
    def _dates(self):
        validate_project_dates(self.start_date, self.expected_completion_date, self.actual_completion_date)
        return self


def validate_project_dates(start, expected, actual):
    if start and expected and expected < start:
        raise ValueError("Expected completion date cannot be before the start date")
    if start and actual and actual < start:
        raise ValueError("Actual completion date cannot be before the start date")
    if actual and actual > dt.date.today():
        raise ValueError("Actual completion date cannot be in the future")


class ProjectUpdateIn(Base):
    name: Name | None = None
    client_id: int | None = None
    description: Text | None = None
    manager_id: int | None = None
    start_date: dt.date | None = None
    expected_completion_date: dt.date | None = None
    actual_completion_date: dt.date | None = None
    budget: NonNegMoney | None = None
    contract_value: NonNegMoney | None = None
    currency: Currency | None = None
    status: ProjectStatus | None = None
    progress: Percent | None = None
    priority: Priority | None = None
    member_ids: list[int] | None = None


class ProjectOut(Out):
    id: int
    code: str
    name: str
    client_id: int
    client_name: str | None = None
    description: str | None
    manager_id: int | None
    manager_name: str | None = None
    start_date: dt.date | None
    expected_completion_date: dt.date | None
    actual_completion_date: dt.date | None
    budget: Decimal | None = None
    contract_value: Decimal | None = None
    currency: str
    status: str
    progress: int
    priority: str
    is_sample: bool
    archived_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime
    is_overdue: bool = False
    open_tasks: int | None = None
    overdue_tasks: int | None = None
    member_ids: list[int] = []


# ---------------------------------------------------------------- quotations
class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    quantity: Annotated[Decimal, Field(ge=0)] | None = None
    unit: Short | None = None
    unit_price: NonNegMoney | None = None
    amount: NonNegMoney | None = None


class QuotationVersionIn(Base):
    quotation_date: dt.date | None = None
    validity_date: dt.date | None = None
    subtotal: NonNegMoney | None = None
    tax_amount: NonNegMoney | None = None
    total_amount: NonNegMoney | None = None
    currency: Currency = "INR"
    payment_terms: Text | None = None
    delivery_terms: Text | None = None
    delivery_date: dt.date | None = None
    scope: Text | None = None
    line_items: list[LineItem] = []
    notes: Text | None = None
    extraction_verified: bool | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.quotation_date and self.validity_date and self.validity_date < self.quotation_date:
            raise ValueError("Validity date cannot be before the quotation date")
        return self


class QuotationCreate(QuotationVersionIn):
    project_id: int
    quotation_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    title: Short | None = None
    document_id: int | None = None


class QuotationStatusIn(Base):
    status: Literal["draft", "submitted", "approved", "rejected"]
    notes: Text | None = None


class ClientPOIn(Base):
    project_id: int
    po_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    issue_date: dt.date | None = None
    po_value: NonNegMoney | None = None
    tax_amount: NonNegMoney | None = None
    total_value: NonNegMoney | None = None
    currency: Currency = "INR"
    delivery_terms: Text | None = None
    payment_terms: Text | None = None
    delivery_date: dt.date | None = None
    scope: Text | None = None
    line_items: list[LineItem] = []
    quotation_version_id: int | None = None
    document_id: int | None = None
    extraction_verified: bool | None = None


class ClientPOUpdate(Base):
    po_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None = None
    issue_date: dt.date | None = None
    po_value: NonNegMoney | None = None
    tax_amount: NonNegMoney | None = None
    total_value: NonNegMoney | None = None
    currency: Currency | None = None
    delivery_terms: Text | None = None
    payment_terms: Text | None = None
    delivery_date: dt.date | None = None
    scope: Text | None = None
    line_items: list[LineItem] | None = None
    quotation_version_id: int | None = None
    document_id: int | None = None
    extraction_verified: bool | None = None


class ClientPODecision(Base):
    status: ClientPOStatus
    review_notes: Text | None = None


# ---------------------------------------------------------------- payments
class PaymentIn(Base):
    project_id: int
    client_po_id: int | None = None
    amount: PosMoney
    payment_date: dt.date | None = None
    due_date: dt.date | None = None
    payment_type: PaymentType = "partial"
    milestone_label: Short | None = None
    method: PaymentMethod | None = None
    transaction_reference: Short | None = None
    bank_reference: Short | None = None
    invoice_reference: Short | None = None
    notes: Text | None = None
    status: Literal["recorded", "pending"] = "recorded"
    allow_overpayment: bool = False
    confirm_possible_duplicate: bool = False

    @model_validator(mode="after")
    def _check(self):
        if self.status == "recorded" and not self.payment_date:
            raise ValueError("Payment date is required for a received payment")
        if self.payment_date and self.payment_date > dt.date.today():
            raise ValueError("Payment date cannot be in the future; record it as a pending payment with a due date")
        if self.status == "pending" and not self.due_date:
            raise ValueError("A pending (expected) payment needs a due date")
        return self


class PaymentUpdate(Base):
    amount: PosMoney | None = None
    payment_date: dt.date | None = None
    due_date: dt.date | None = None
    payment_type: PaymentType | None = None
    milestone_label: Short | None = None
    method: PaymentMethod | None = None
    transaction_reference: Short | None = None
    bank_reference: Short | None = None
    invoice_reference: Short | None = None
    notes: Text | None = None
    client_po_id: int | None = None
    allow_overpayment: bool = False


class PaymentStatusIn(Base):
    status: PaymentStatus
    payment_date: dt.date | None = None
    notes: Text | None = None
    allow_overpayment: bool = False


# ---------------------------------------------------------------- suppliers & procurement
class SupplierIn(Base):
    name: Name
    contact_person: Short | None = None
    email: EmailStr | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9+()\-\s]{6,20}$")] | None = None
    address: Text | None = None
    gstin: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True)] | None = None

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v):
        if v and not GSTIN_RE.match(v):
            raise ValueError("GSTIN must be a valid 15-character GST number")
        return v


class BOMItemIn(Base):
    project_id: int
    item_name: Name
    description: Text | None = None
    specification: Text | None = None
    quantity: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)] = "nos"
    estimated_rate: NonNegMoney | None = None
    actual_rate: NonNegMoney | None = None
    supplier_id: int | None = None
    required_date: dt.date | None = None
    procurement_status: ProcurementStatus = "pending"
    received_quantity: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)] = Decimal(0)
    remarks: Text | None = None


class BOMItemUpdate(Base):
    item_name: Name | None = None
    description: Text | None = None
    specification: Text | None = None
    quantity: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)] | None = None
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)] | None = None
    estimated_rate: NonNegMoney | None = None
    actual_rate: NonNegMoney | None = None
    supplier_id: int | None = None
    required_date: dt.date | None = None
    procurement_status: ProcurementStatus | None = None
    received_quantity: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)] | None = None
    remarks: Text | None = None


class SupplierPOItemIn(Base):
    bom_item_id: int | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    quantity: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)] = "nos"
    unit_price: NonNegMoney
    tax_rate: Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] = Decimal(0)
    received_quantity: Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)] = Decimal(0)


class SupplierPOIn(Base):
    project_id: int
    supplier_id: int
    po_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    po_date: dt.date | None = None
    delivery_date: dt.date | None = None
    actual_delivery_date: dt.date | None = None
    currency: Currency = "INR"
    payment_terms: Text | None = None
    status: SupplierPOStatus = "ordered"
    notes: Text | None = None
    document_id: int | None = None
    items: list[SupplierPOItemIn] = Field(min_length=1)


class SupplierPOUpdate(Base):
    po_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None = None
    po_date: dt.date | None = None
    delivery_date: dt.date | None = None
    actual_delivery_date: dt.date | None = None
    currency: Currency | None = None
    payment_terms: Text | None = None
    status: SupplierPOStatus | None = None
    notes: Text | None = None
    document_id: int | None = None
    items: list[SupplierPOItemIn] | None = None


class SupplierPaymentIn(Base):
    supplier_po_id: int
    amount: PosMoney
    payment_date: dt.date
    method: PaymentMethod | None = None
    reference: Short | None = None
    status: SupplierPaymentStatus = "recorded"
    notes: Text | None = None

    @field_validator("payment_date")
    @classmethod
    def _date(cls, v):
        if v > dt.date.today():
            raise ValueError("Payment date cannot be in the future")
        return v


class SupplierPaymentStatusIn(Base):
    status: SupplierPaymentStatus


# ---------------------------------------------------------------- tasks, updates, events
class TaskIn(Base):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    description: Text | None = None
    project_id: int | None = None
    assignee_id: int | None = None
    priority: Priority = "medium"
    status: TaskStatus = "todo"
    progress: Percent = 0
    start_date: dt.date | None = None
    due_date: dt.date | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("Due date cannot be before the start date")
        return self


class TaskUpdate(Base):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None
    description: Text | None = None
    project_id: int | None = None
    assignee_id: int | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    progress: Percent | None = None
    start_date: dt.date | None = None
    due_date: dt.date | None = None


class UpdateIn(Base):
    project_id: int
    update_at: dt.datetime | None = None
    health: Health = "on_track"
    work_completed: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
    progress: Percent
    work_in_progress: Text | None = None
    blockers: Text | None = None
    risks: Text | None = None
    materials_required: Text | None = None
    next_steps: Text | None = None
    planned_completion_date: dt.date | None = None
    remarks: Text | None = None
    apply_progress_to_project: bool = True


class UpdateEdit(Base):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=255)]
    health: Health | None = None
    work_completed: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)] | None = None
    progress: Percent | None = None
    work_in_progress: Text | None = None
    blockers: Text | None = None
    risks: Text | None = None
    materials_required: Text | None = None
    next_steps: Text | None = None
    planned_completion_date: dt.date | None = None
    remarks: Text | None = None


class EventIn(Base):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    description: Text | None = None
    event_type: EventType = "meeting"
    start_at: dt.datetime
    end_at: dt.datetime | None = None
    all_day: bool = False
    location: Short | None = None
    project_id: int | None = None
    client_id: int | None = None
    task_id: int | None = None
    remind_minutes_before: Annotated[int, Field(ge=0, le=43200)] | None = None

    @model_validator(mode="after")
    def _check(self):
        for v in (self.start_at, self.end_at):
            if v is not None and v.tzinfo is None:
                raise ValueError("Datetimes must include a timezone offset (ISO 8601)")
        if self.end_at and self.end_at < self.start_at:
            raise ValueError("End time cannot be before the start time")
        return self


class EventUpdate(Base):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None
    description: Text | None = None
    event_type: EventType | None = None
    start_at: dt.datetime | None = None
    end_at: dt.datetime | None = None
    all_day: bool | None = None
    location: Short | None = None
    project_id: int | None = None
    client_id: int | None = None
    task_id: int | None = None
    remind_minutes_before: Annotated[int, Field(ge=0, le=43200)] | None = None


# ---------------------------------------------------------------- settings & reports
class UserSettingsIn(Base):
    reminders_enabled: bool | None = None
    reminder_interval_minutes: Annotated[int, Field(ge=15, le=1440)] | None = None
    work_start: dt.time | None = None
    work_end: dt.time | None = None
    work_days: list[Annotated[int, Field(ge=0, le=6)]] | None = None
    timezone: Short | None = None
    notify_email: bool | None = None
    disabled_notification_types: list[str] | None = None


class SystemRulesIn(Base):
    deadline_warning_days: Annotated[int, Field(ge=1, le=60)] | None = None
    quotation_expiry_warning_days: Annotated[int, Field(ge=1, le=90)] | None = None
    missing_update_days: Annotated[int, Field(ge=1, le=60)] | None = None
    supplier_delay_grace_days: Annotated[int, Field(ge=0, le=30)] | None = None
    enabled_rules: list[str] | None = None


class ReportRequest(Base):
    period_type: Literal["weekly", "monthly", "quarterly", "annual", "custom"] = "weekly"
    scope: Literal["company", "project"] = "company"
    project_id: int | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    client_id: int | None = None
    manager_id: int | None = None
    status: ProjectStatus | None = None
    use_ai: bool = True

    @model_validator(mode="after")
    def _check(self):
        if self.scope == "project" and not self.project_id:
            raise ValueError("Select a project for a project report")
        if self.period_type == "custom":
            if not (self.start_date and self.end_date):
                raise ValueError("Custom reports need a start and end date")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("End date cannot be before start date")
        return self
