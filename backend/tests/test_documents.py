import os

from conftest import make_pdf


def _upload(api, project_id, name, data, category="other", **extra):
    return api.post("/api/documents", files={"file": (name, data)}, data={"project_id": str(project_id), "category": category, **extra})


def test_upload_pdf_extracts_quotation_fields(pm, project):
    pdf = make_pdf(["QUOTATION", "Quotation No: PIPL/Q/2026/077", "Date: 05/10/2026", "Valid until: 04/11/2026",
                    "Sub Total: 1,00,000.00", "GST 18%: 18,000.00", "Grand Total: 1,18,000.00", "Payment Terms: 30% advance"])
    r = _upload(pm, project["id"], "quote.pdf", pdf, category="quotation")
    assert r.status_code == 201, r.text
    body = r.json()
    f = body["extraction"]["fields"]
    assert f["number"]["value"] == "PIPL/Q/2026/077"
    assert f["total_amount"]["value"] in ("118000.00", "118000")
    assert all(v["confidence"] in ("high", "medium", "low", "missing") for v in f.values())
    assert body["document"]["sha256"]


def test_rejects_disallowed_and_mismatched_files(pm, project):
    r = _upload(pm, project["id"], "tool.exe", b"MZ\x90\x00binary")
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_file_type"
    r = _upload(pm, project["id"], "fake.pdf", b"this is not really a pdf")
    assert r.status_code == 422 and r.json()["error"]["code"] == "content_mismatch"
    r = _upload(pm, project["id"], "empty.txt", b"")
    assert r.status_code == 422


def test_path_traversal_filename_is_not_used_on_disk(pm, project):
    r = _upload(pm, project["id"], "../../etc/passwd.txt", b"hello")
    assert r.status_code == 201
    d = r.json()["document"]
    assert "/" not in d.get("stored_filename", "x") and ".." not in d.get("stored_filename", "x")


def test_missing_file_on_disk_returns_clear_error(pm, project, db):
    from app import models as m
    from app.storage import storage_root

    r = _upload(pm, project["id"], "notes.txt", b"site notes")
    doc = db.get(m.Document, r.json()["document"]["id"])
    os.remove(storage_root() / doc.stored_filename)
    r = pm.get(f"/api/documents/{doc.id}/download")
    assert r.status_code == 404 and r.json()["error"]["code"] == "file_missing"


def test_document_access_follows_project_visibility(pm, member, project, users):
    secret = pm.post("/api/projects", json={"name": "Private", "client_id": project["client_id"]}).json()
    r = _upload(pm, secret["id"], "secret.txt", b"confidential")
    did = r.json()["document"]["id"]
    assert member.get(f"/api/documents/{did}/download").status_code == 404
    assert member.get(f"/api/documents/{did}/preview").status_code == 404
    assert _upload(member, secret["id"], "x.txt", b"x").status_code == 404


def test_replace_keeps_history(pm, project):
    first = _upload(pm, project["id"], "drawing.txt", b"rev A").json()["document"]
    r = pm.post(f"/api/documents/{first['id']}/replace", files={"file": ("drawing.txt", b"rev B")})
    assert r.status_code == 201
    old = pm.get(f"/api/documents/{first['id']}").json()
    old = old.get("document", old)
    assert old["superseded_by_id"]
    assert pm.get(f"/api/documents/{first['id']}/download").content == b"rev A"


def test_docx_preview_is_sanitised(pm, project):
    from io import BytesIO

    from docx import Document

    d = Document()
    d.add_paragraph("<script>alert(1)</script> Scope of supply")
    buf = BytesIO()
    d.save(buf)
    did = _upload(pm, project["id"], "scope.docx", buf.getvalue()).json()["document"]["id"]
    r = pm.get(f"/api/documents/{did}/preview")
    assert r.status_code == 200
    assert "<script>" not in r.text
