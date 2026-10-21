from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import models as m
from ..core import MANAGE_ROLES, bad_request, can_view_finance, like, visible_project_ids_subquery
from ..db import get_db
from ..routers.documents import FINANCIAL_CATEGORIES
from ..security import get_current_user

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def global_search(q: str, limit: int = 6, db: Session = Depends(get_db), user: m.User = Depends(get_current_user)):
    q = q.strip()
    if len(q) < 2:
        raise bad_request("Enter at least 2 characters to search")
    limit = min(max(limit, 1), 20)
    t = like(q)
    visible = visible_project_ids_subquery(user)
    results: dict[str, list] = {}

    projects = db.scalars(select(m.Project).where(m.Project.id.in_(visible), or_(m.Project.name.ilike(t), m.Project.code.ilike(t),
                                                                                    m.Project.description.ilike(t))).limit(limit)).all()
    results["projects"] = [{"id": p.id, "title": f"{p.code} · {p.name}", "subtitle": p.status, "link": f"/projects/{p.id}"} for p in projects]

    cstmt = select(m.Client).where(or_(m.Client.name.ilike(t), m.Client.company_name.ilike(t), m.Client.gstin.ilike(t),
                                       m.Client.contact_person.ilike(t)))
    if user.role not in MANAGE_ROLES:
        cstmt = cstmt.where(m.Client.id.in_(select(m.Project.client_id).where(m.Project.id.in_(visible))))
    results["clients"] = [{"id": c.id, "title": c.company_name, "subtitle": c.contact_person, "link": f"/clients/{c.id}"}
                          for c in db.scalars(cstmt.limit(limit))]

    if can_view_finance(user):
        qs = db.scalars(select(m.Quotation).where(m.Quotation.project_id.in_(visible),
                                                  or_(m.Quotation.quotation_number.ilike(t), m.Quotation.title.ilike(t))).limit(limit)).all()
        results["quotations"] = [{"id": x.id, "title": x.quotation_number, "subtitle": x.title,
                                  "link": f"/projects/{x.project_id}?tab=quotation"} for x in qs]
        pos = db.scalars(select(m.ClientPurchaseOrder).where(m.ClientPurchaseOrder.project_id.in_(visible),
                                                             m.ClientPurchaseOrder.po_number.ilike(t)).limit(limit)).all()
        spos = db.scalars(select(m.SupplierPurchaseOrder).where(m.SupplierPurchaseOrder.project_id.in_(visible),
                                                                m.SupplierPurchaseOrder.po_number.ilike(t)).limit(limit)).all()
        results["purchase_orders"] = (
            [{"id": x.id, "title": f"Client PO {x.po_number}", "subtitle": x.status, "link": f"/projects/{x.project_id}?tab=client-po"} for x in pos]
            + [{"id": x.id, "title": f"Supplier PO {x.po_number}", "subtitle": x.supplier.name, "link": f"/projects/{x.project_id}?tab=bom"} for x in spos]
        )

    dstmt = select(m.Document).where(m.Document.deleted_at.is_(None), m.Document.project_id.in_(visible),
                                     or_(m.Document.title.ilike(t), m.Document.original_filename.ilike(t), m.Document.extracted_text.ilike(t)))
    if not can_view_finance(user):
        dstmt = dstmt.where(m.Document.category.not_in(FINANCIAL_CATEGORIES))
    results["documents"] = [{"id": d.id, "title": d.title, "subtitle": d.category, "link": f"/documents?doc={d.id}"}
                            for d in db.scalars(dstmt.order_by(m.Document.created_at.desc()).limit(limit))]

    tstmt = select(m.Task).where(m.Task.deleted_at.is_(None), or_(m.Task.title.ilike(t), m.Task.description.ilike(t)))
    if user.role not in MANAGE_ROLES:
        tstmt = tstmt.where(or_(m.Task.assignee_id == user.id, m.Task.project_id.in_(visible)))
    results["tasks"] = [{"id": x.id, "title": x.title, "subtitle": x.status, "link": f"/tasks?task={x.id}"} for x in db.scalars(tstmt.limit(limit))]

    ups = db.scalars(select(m.ProjectUpdate).where(m.ProjectUpdate.project_id.in_(visible),
                                                   or_(m.ProjectUpdate.work_completed.ilike(t), m.ProjectUpdate.blockers.ilike(t),
                                                       m.ProjectUpdate.next_steps.ilike(t)))
                     .order_by(m.ProjectUpdate.update_at.desc()).limit(limit)).all()
    results["updates"] = [{"id": u.id, "title": (u.work_completed or "")[:80], "subtitle": u.update_at.date().isoformat(),
                           "link": f"/updates?update={u.id}"} for u in ups]
    return {"query": q, "results": results, "total": sum(len(v) for v in results.values())}
