import datetime as dt

from conftest import approve_quotation


def _quote(pm, project, **kw):
    body = {"project_id": project["id"], "quotation_number": "Q-100", "total_amount": "118000.00", "subtotal": "100000.00",
            "tax_amount": "18000.00", "quotation_date": str(dt.date.today()), **kw}
    r = pm.post("/api/quotations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_quotation_revisions_and_superseding(pm, project):
    q = _quote(pm, project)
    v1 = q["latest"]
    assert v1["revision_number"] == 0 and v1["status"] == "draft"  # R0, R1, ... as on PIPL quotations
    r = pm.post(f"/api/quotations/{q['id']}/versions", json={"total_amount": "120000.00", "subtotal": "101694.92", "tax_amount": "18305.08"})
    assert r.status_code == 201
    versions = {v["revision_number"]: v for v in r.json()["versions"]}
    assert versions[1]["status"] == "draft"
    assert versions[0]["status"] == "superseded"  # previous open revision preserved, not overwritten
    assert versions[0]["total_amount"] in ("118000.00", "118000")


def test_duplicate_quotation_number_per_client_rejected(pm, project):
    _quote(pm, project)
    r = pm.post("/api/quotations", json={"project_id": project["id"], "quotation_number": "Q-100"})
    assert r.status_code == 409


def test_approval_rules_and_locking(pm, project):
    q = _quote(pm, project, total_amount="120000.00")  # subtotal + tax != total
    vid = q["latest"]["id"]
    r = pm.post(f"/api/quotation-versions/{vid}/status", json={"status": "approved"})
    assert r.status_code == 422
    assert pm.patch(f"/api/quotation-versions/{vid}", json={"total_amount": "118000.00", "subtotal": "100000.00", "tax_amount": "18000.00"}).status_code == 200
    assert pm.post(f"/api/quotation-versions/{vid}/status", json={"status": "approved"}).status_code == 200
    r = pm.patch(f"/api/quotation-versions/{vid}", json={"total_amount": "1.00"})
    assert r.status_code == 409  # approved revisions are locked
    assert pm.post(f"/api/quotation-versions/{vid}/status", json={"status": "submitted"}).status_code == 409


def test_only_one_approved_quotation_per_project(pm, project):
    first = approve_quotation(pm, project["id"], number="Q-A")
    approve_quotation(pm, project["id"], total="200000.00", number="Q-B")
    q = pm.get(f"/api/quotations/{first['id']}").json()
    assert q["versions"][0]["status"] == "superseded"


def test_unverified_extraction_blocks_approval(pm, project, db):
    from app import models as m

    q = _quote(pm, project)
    v = db.get(m.QuotationVersion, q["latest"]["id"])
    v.extraction = {"fields": {"total_amount": {"value": "118000", "confidence": "low"}}}
    v.extraction_verified = False
    db.commit()
    r = pm.post(f"/api/quotation-versions/{v.id}/status", json={"status": "approved"})
    assert r.status_code == 422 and "verified" in r.json()["error"]["message"]


def test_po_comparison_flags_discrepancies(pm, project):
    approve_quotation(pm, project["id"], total="118000.00", subtotal="100000.00", tax="18000.00")
    po = pm.post("/api/client-pos", json={"project_id": project["id"], "po_number": "PO-1", "po_value": "100000.00",
                                          "tax_amount": "18000.00", "total_value": "110000.00", "currency": "USD"})
    assert po.status_code == 201, po.text
    detail = pm.get(f"/api/client-pos/{po.json()['id']}").json()
    cmp = detail["comparison"]
    assert cmp["discrepancy_count"] >= 2
    labels = {r["field"] if "field" in r else r.get("label"): r["status"] for r in cmp["rows"]}
    assert "mismatch" in labels.values()
    # verifying requires an explicit acknowledgement and review notes; it is never automatic
    r = pm.post(f"/api/client-pos/{po.json()['id']}/decision", json={"status": "verified"})
    assert r.status_code == 409
    r = pm.post(f"/api/client-pos/{po.json()['id']}/decision", params={"acknowledge_discrepancies": True},
                json={"status": "verified", "review_notes": "Client agreed revised value by email"})
    assert r.status_code == 200
    hist = pm.get(f"/api/client-pos/{po.json()['id']}").json()["history"]
    assert any(h["action"] == "decision_verified" for h in hist)


def test_matching_po_verifies_cleanly(pm, project):
    approve_quotation(pm, project["id"], total="118000.00", subtotal="100000.00", tax="18000.00")
    po = pm.post("/api/client-pos", json={"project_id": project["id"], "po_number": "PO-2", "po_value": "100000.00",
                                          "tax_amount": "18000.00", "total_value": "118000.00"}).json()
    detail = pm.get(f"/api/client-pos/{po['id']}").json()
    assert all(r["status"] != "mismatch" for r in detail["comparison"]["rows"])
    assert pm.post(f"/api/client-pos/{po['id']}/decision", json={"status": "verified"}).status_code == 200
