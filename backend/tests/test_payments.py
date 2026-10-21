import datetime as dt
from decimal import Decimal

from conftest import approve_quotation, pay, receivable


def _verify(api, pid):
    r = api.post(f"/api/payments/{pid}/status", json={"status": "verified"})
    assert r.status_code == 200, r.text
    return r.json()


def test_x_minus_y_equals_z_with_partial_payments(pm, project):
    approve_quotation(pm, project["id"], total="100000.00")
    p1 = pay(pm, project["id"], "30000.00", ref="TXN-1").json()["payment"]
    p2 = pay(pm, project["id"], "25000.50", ref="TXN-2").json()["payment"]
    r = receivable(pm, project["id"])
    assert Decimal(r["contract_value"]) == Decimal("100000.00")
    assert Decimal(r["verified_received"]) == 0  # recorded but unverified payments do not reduce Z
    assert Decimal(r["unverified_recorded"]) == Decimal("55000.50")
    _verify(pm, p1["id"])
    _verify(pm, p2["id"])
    r = receivable(pm, project["id"])
    assert Decimal(r["verified_received"]) == Decimal("55000.50")
    assert Decimal(r["outstanding"]) == Decimal("44999.50")
    assert Decimal(r["contract_value"]) - Decimal(r["verified_received"]) == Decimal(r["outstanding"])
    assert r["contract_basis"] == "approved_quotation"


def test_verified_client_po_takes_precedence_for_x(pm, project):
    approve_quotation(pm, project["id"], total="100000.00")
    po = pm.post("/api/client-pos", json={"project_id": project["id"], "po_number": "PO-9", "total_value": "100000.00"}).json()
    assert pm.post(f"/api/client-pos/{po['id']}/decision", json={"status": "verified"}).status_code == 200
    r = receivable(pm, project["id"])
    assert r["contract_basis"] == "verified_client_po"


def test_overpayment_requires_confirmation_and_creates_credit(pm, project):
    approve_quotation(pm, project["id"], total="50000.00")
    first = pay(pm, project["id"], "40000.00", ref="A1").json()["payment"]
    _verify(pm, first["id"])
    r = pay(pm, project["id"], "15000.00", ref="A2")
    assert r.status_code == 409 and r.json()["error"]["code"] == "overpayment"
    r = pay(pm, project["id"], "15000.00", ref="A2", allow_overpayment=True)
    assert r.status_code == 201
    _verify(pm, r.json()["payment"]["id"])
    rec = receivable(pm, project["id"])
    assert Decimal(rec["outstanding"]) == 0  # Z never goes negative
    assert Decimal(rec["credit"]) == Decimal("5000.00")


def test_duplicate_transaction_reference_rejected(pm, project):
    approve_quotation(pm, project["id"])
    assert pay(pm, project["id"], "1000.00", ref="UTR123").status_code == 201
    r = pay(pm, project["id"], "2000.00", ref="utr123")
    assert r.status_code == 409


def test_possible_duplicate_needs_confirmation(pm, project):
    approve_quotation(pm, project["id"])
    assert pay(pm, project["id"], "1000.00").status_code == 201
    r = pay(pm, project["id"], "1000.00")
    assert r.status_code == 409 and r.json()["error"]["code"] == "possible_duplicate"
    assert pay(pm, project["id"], "1000.00", confirm_possible_duplicate=True).status_code == 201


def test_payment_validation(pm, project):
    approve_quotation(pm, project["id"])
    assert pay(pm, project["id"], "0").status_code == 422
    assert pay(pm, project["id"], "-5").status_code == 422
    future = str(dt.date.today() + dt.timedelta(days=3))
    assert pay(pm, project["id"], "100", payment_date=future).status_code == 422
    r = pm.post("/api/payments", json={"project_id": project["id"], "amount": "100", "status": "pending"})
    assert r.status_code == 422  # pending needs a due date


def test_failed_and_reversed_payments_do_not_count(pm, project):
    approve_quotation(pm, project["id"], total="10000.00")
    p = pay(pm, project["id"], "4000.00", ref="R1").json()["payment"]
    _verify(pm, p["id"])
    assert pm.post(f"/api/payments/{p['id']}/status", json={"status": "reversed"}).status_code == 200
    rec = receivable(pm, project["id"])
    assert Decimal(rec["verified_received"]) == 0 and Decimal(rec["outstanding"]) == Decimal("10000.00")
    assert pm.patch(f"/api/payments/{p['id']}", json={"amount": "1"}).status_code == 409  # reversed is locked


def test_pending_payment_overdue_tracking(pm, project, db):
    approve_quotation(pm, project["id"], total="10000.00")
    r = pay(pm, project["id"], "3000.00", status="pending", milestone_label="Dispatch")
    assert r.status_code == 201
    from app import models as m

    p = db.get(m.PaymentReceived, r.json()["payment"]["id"])
    p.due_date = dt.date.today() - dt.timedelta(days=2)
    db.commit()
    rec = receivable(pm, project["id"])
    assert Decimal(rec["overdue_pending"]) == Decimal("3000.00") and rec["overdue_count"] == 1
    assert Decimal(rec["outstanding"]) == Decimal("10000.00")  # expected money is not received money


def test_supplier_payments_excluded_from_receivables(pm, project):
    approve_quotation(pm, project["id"], total="100000.00")
    sup = pm.post("/api/suppliers", json={"name": "Steel Co"}).json()
    po = pm.post("/api/supplier-pos", json={"project_id": project["id"], "supplier_id": sup["id"], "po_number": "SPO-1",
                                            "items": [{"description": "Plates", "quantity": "10", "unit_price": "1000", "tax_rate": "18"}]})
    assert po.status_code == 201, po.text
    sp = pm.post("/api/supplier-payments", json={"supplier_po_id": po.json()["id"], "amount": "5000.00", "payment_date": str(dt.date.today()), "reference": "S-1"})
    assert sp.status_code == 201, sp.text
    rec = receivable(pm, project["id"])
    assert Decimal(rec["verified_received"]) == 0 and Decimal(rec["outstanding"]) == Decimal("100000.00")
    summary = pm.get("/api/payments/summary").json()
    assert summary["totals_by_currency"]["INR"]["verified_received"] in ("0.00", "0")


def test_payment_export(pm, project):
    approve_quotation(pm, project["id"])
    pay(pm, project["id"], "1000.00", ref="=HYPERLINK(\"x\")")
    r = pm.get("/api/payments/export", params={"format": "csv"})
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert "'=HYPERLINK" in r.text  # spreadsheet formula injection neutralised
    r = pm.get("/api/payments/export", params={"format": "xlsx"})
    assert r.status_code == 200 and r.content[:2] == b"PK"
