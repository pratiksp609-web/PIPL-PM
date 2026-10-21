import datetime as dt
from decimal import Decimal


def _setup(pm, project):
    sup = pm.post("/api/suppliers", json={"name": "Pumps Ltd"}).json()
    bom = pm.post("/api/bom-items", json={"project_id": project["id"], "item_name": "Pump 5 kW", "quantity": "2",
                                          "unit": "nos", "estimated_rate": "50000"})
    assert bom.status_code == 201, bom.text
    return sup, bom.json()


def test_duplicate_supplier_rejected(pm):
    assert pm.post("/api/suppliers", json={"name": "Steel Traders"}).status_code == 201
    assert pm.post("/api/suppliers", json={"name": "steel traders"}).status_code == 409


def test_supplier_po_totals_and_bom_sync(pm, project):
    sup, bom = _setup(pm, project)
    r = pm.post("/api/supplier-pos", json={
        "project_id": project["id"], "supplier_id": sup["id"], "po_number": "SPO-10",
        "delivery_date": str(dt.date.today() + dt.timedelta(days=5)),
        "items": [{"bom_item_id": bom["id"], "description": "Pump 5 kW", "quantity": "2", "unit_price": "48000", "tax_rate": "18"}],
    })
    assert r.status_code == 201, r.text
    po = r.json()
    assert Decimal(po["subtotal"]) == Decimal("96000.00")
    assert Decimal(po["tax_amount"]) == Decimal("17280.00")
    assert Decimal(po["total_amount"]) == Decimal("113280.00")
    b = pm.get("/api/bom-items", params={"project_id": project["id"]}).json()["items"][0]
    assert Decimal(b["actual_rate"]) == Decimal("48000.00")
    assert b["procurement_status"] == "ordered" and b["supplier_id"] == sup["id"]
    s = pm.get(f"/api/projects/{project['id']}/procurement").json()
    assert Decimal(s["estimated_cost"]) == Decimal("100000.00")
    assert Decimal(s["committed_cost"]) == Decimal("113280.00")


def test_receiving_updates_status(pm, project):
    sup, bom = _setup(pm, project)
    po = pm.post("/api/supplier-pos", json={"project_id": project["id"], "supplier_id": sup["id"], "po_number": "SPO-11",
                                            "items": [{"bom_item_id": bom["id"], "description": "Pump", "quantity": "2", "unit_price": "1000"}]}).json()
    item = po["items"][0]
    r = pm.post(f"/api/supplier-pos/{po['id']}/receive", json=[{"item_id": item["id"], "received_quantity": "3"}])
    assert r.status_code == 422  # cannot receive more than ordered
    r = pm.post(f"/api/supplier-pos/{po['id']}/receive", json=[{"item_id": item["id"], "received_quantity": "1"}])
    assert r.status_code == 200 and r.json()["status"] == "partially_received"
    r = pm.post(f"/api/supplier-pos/{po['id']}/receive", json=[{"item_id": item["id"], "received_quantity": "2"}])
    assert r.json()["status"] == "received"
    b = pm.get("/api/bom-items", params={"project_id": project["id"]}).json()["items"][0]
    assert b["procurement_status"] == "received" and Decimal(b["received_quantity"]) == 2


def test_supplier_payment_limits(pm, project):
    sup, bom = _setup(pm, project)
    po = pm.post("/api/supplier-pos", json={"project_id": project["id"], "supplier_id": sup["id"], "po_number": "SPO-12",
                                            "items": [{"description": "Pump", "quantity": "1", "unit_price": "1000"}]}).json()
    today = str(dt.date.today())
    assert pm.post("/api/supplier-payments", json={"supplier_po_id": po["id"], "amount": "1500", "payment_date": today}).status_code == 409
    assert pm.post("/api/supplier-payments", json={"supplier_po_id": po["id"], "amount": "600", "payment_date": today, "reference": "SP-1"}).status_code == 201
    assert pm.post("/api/supplier-payments", json={"supplier_po_id": po["id"], "amount": "100", "payment_date": today, "reference": "sp-1"}).status_code == 409
    assert pm.post("/api/supplier-payments", json={"supplier_po_id": po["id"], "amount": "500", "payment_date": today}).status_code == 409
    got = pm.get(f"/api/supplier-pos/{po['id']}").json()
    got = got.get("po", got)
    assert Decimal(got["paid_amount"]) == Decimal("600.00") and Decimal(got["balance_due"]) == Decimal("400.00")


def test_bom_on_active_po_cannot_be_deleted(pm, project):
    sup, bom = _setup(pm, project)
    pm.post("/api/supplier-pos", json={"project_id": project["id"], "supplier_id": sup["id"], "po_number": "SPO-13",
                                       "items": [{"bom_item_id": bom["id"], "description": "Pump", "quantity": "1", "unit_price": "1"}]})
    assert pm.delete(f"/api/bom-items/{bom['id']}").status_code == 409


def test_member_sees_bom_without_prices(member, pm, project):
    _setup(pm, project)
    items = member.get("/api/bom-items", params={"project_id": project["id"]}).json()["items"]
    assert items and items[0]["estimated_rate"] is None and "estimated_total" not in items[0]
