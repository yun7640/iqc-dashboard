"""월별 검토 · 전자서명 · 감사추적 · PDF 라우트 (4.3 / 4.4)."""
from io import BytesIO
from datetime import datetime

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, send_file, abort)
from flask_login import login_required, current_user

from .. import db
from ..models import (Instrument, MonthlyReview, Signature, Capa, QcTarget,
                      QcResult, CommentTemplate, QcMaterial)
from ..services import (build_precision_table, log_audit, prev_month,
                        analyte_match_report, assigned_analyte_names,
                        grouped_criteria, can_act_as)
from ..westgard import RULE_INFO
from ..pdf_report import build_pdf

bp = Blueprint("review", __name__, url_prefix="/review")


def _get_or_create_review(inst_id, ym):
    review = MonthlyReview.query.filter_by(
        instrument_id=inst_id, year_month=ym).first()
    if not review:
        review = MonthlyReview(instrument_id=inst_id, year_month=ym,
                               status="draft")
        db.session.add(review)
        db.session.commit()
    return review


@bp.route("/")
@login_required
def index():
    reviews = (MonthlyReview.query
               .order_by(MonthlyReview.year_month.desc()).all())
    instruments = Instrument.query.all()
    return render_template("review_list.html", reviews=reviews,
                           instruments=instruments)


@bp.route("/<int:inst_id>/<ym>")
@login_required
def detail(inst_id, ym):
    inst = db.get_or_404(Instrument, inst_id)
    review = _get_or_create_review(inst_id, ym)
    rows = build_precision_table(inst_id, ym)

    # 멀티룰 위반 상세
    violations = []
    for r in rows:
        if r["n_reject"] or r["n_warn"]:
            recs = (QcResult.query.filter_by(target_id=r["target"].id)
                    .filter(QcResult.status.in_(["reject", "warning"]))
                    .filter(db.extract("year", QcResult.result_date) == int(ym[:4]))
                    .filter(db.extract("month", QcResult.result_date) == int(ym[5:7]))
                    .order_by(QcResult.result_date).all())
            for rec in recs:
                violations.append({
                    "analyte": r["analyte"], "level": r["level"],
                    "date": rec.result_date, "value": rec.value,
                    "z": rec.z_score, "status": rec.status,
                    "rules": rec.rules,
                    "demo": bool(rec.action and "데모" in rec.action),
                })

    summary = {
        "total": len(rows),
        "flagged": sum(1 for r in rows if not r["pass"]),
        "rejects": sum(r["n_reject"] for r in rows),
        "warns": sum(r["n_warn"] for r in rows),
    }
    signatures = {s.role: s for s in review.signatures}
    integrity_ok = None
    if signatures:
        integrity_ok = all(s.content_hash == review.content_hash()
                           for s in review.signatures)
    capas = Capa.query.filter_by(review_id=review.id).all()

    # 검토의견 문구 템플릿 (역할별) + 삽입용 id→body 맵
    mgr_tpl = (CommentTemplate.query.filter_by(role="qc_manager", active=True)
               .order_by(CommentTemplate.display_order, CommentTemplate.id).all())
    pat_tpl = (CommentTemplate.query.filter_by(role="pathologist", active=True)
               .order_by(CommentTemplate.display_order, CommentTemplate.id).all())
    tpl_map = {t.id: t.body for t in mgr_tpl + pat_tpl}

    materials = (QcMaterial.query.filter_by(selected=True)
                 .order_by(QcMaterial.display_order, QcMaterial.id).all())

    # 평가장비별 검사항목 연동 + LIS 결과 매칭 점검
    match = analyte_match_report(inst_id, ym)
    assigned_names = assigned_analyte_names(inst_id)
    crit_groups = grouped_criteria(rows)
    can_mgr = can_act_as(inst, current_user, "qc_manager")
    can_pat = can_act_as(inst, current_user, "pathologist")

    return render_template("review_detail.html", inst=inst, review=review,
                           rows=rows, violations=violations, summary=summary,
                           signatures=signatures, capas=capas,
                           integrity_ok=integrity_ok, rule_info=RULE_INFO,
                           prev_ym=prev_month(ym),
                           mgr_tpl=mgr_tpl, pat_tpl=pat_tpl, tpl_map=tpl_map,
                           materials=materials, match=match,
                           assigned_names=assigned_names, crit_groups=crit_groups,
                           can_mgr=can_mgr, can_pat=can_pat)


@bp.route("/<int:review_id>/comment", methods=["POST"])
@login_required
def save_comment(review_id):
    review = db.get_or_404(MonthlyReview, review_id)
    if review.status == "completed":
        flash("검토완료 상태에서는 수정할 수 없습니다.", "warning")
        return redirect(url_for("review.detail",
                        inst_id=review.instrument_id, ym=review.year_month))
    field = request.form.get("field")
    text = request.form.get("text", "")
    inst = db.session.get(Instrument, review.instrument_id)
    if field == "manager" and can_act_as(inst, current_user, "qc_manager"):
        review.manager_comment = text
    elif field == "pathologist" and can_act_as(inst, current_user, "pathologist"):
        review.pathologist_comment = text
    else:
        flash("이 장비에 지정된 담당자/전문의만 해당 검토의견을 작성할 수 있습니다.", "danger")
        return redirect(url_for("review.detail",
                        inst_id=review.instrument_id, ym=review.year_month))
    review.updated_at = datetime.utcnow()
    db.session.commit()
    log_audit("COMMENT", entity="monthly_review", entity_id=review.id,
              detail=f"{field} 검토의견 저장")
    flash("검토의견이 저장되었습니다.", "success")
    return redirect(url_for("review.detail",
                    inst_id=review.instrument_id, ym=review.year_month))


@bp.route("/<int:review_id>/sign", methods=["POST"])
@login_required
def sign(review_id):
    """전자서명 — 비밀번호 재인증 + 무결성 해시 저장."""
    review = db.get_or_404(MonthlyReview, review_id)
    password = request.form.get("password", "")
    role = current_user.role

    # 권한 확인 — 이 장비에 지정된 담당자/전문의만 서명 가능
    inst = db.session.get(Instrument, review.instrument_id)
    if role not in ("qc_manager", "pathologist") or not can_act_as(inst, current_user, role):
        flash("이 장비에 지정된 담당자/전문의만 전자서명할 수 있습니다.", "danger")
        return redirect(url_for("review.detail",
                        inst_id=review.instrument_id, ym=review.year_month))

    # 비밀번호 재인증
    if not current_user.check_password(password):
        log_audit("SIGN_FAIL", entity="monthly_review", entity_id=review.id,
                  detail=f"{current_user.name} 서명 비밀번호 재인증 실패")
        flash("비밀번호 재인증에 실패했습니다. 서명이 취소되었습니다.", "danger")
        return redirect(url_for("review.detail",
                        inst_id=review.instrument_id, ym=review.year_month))

    # 순서 통제: 담당 서명 후 전문의 서명
    existing = {s.role for s in review.signatures}
    if role == "pathologist" and "qc_manager" not in existing:
        flash("정도관리담당 서명 이후에 전문의 서명이 가능합니다.", "warning")
        return redirect(url_for("review.detail",
                        inst_id=review.instrument_id, ym=review.year_month))
    if role in existing:
        flash("이미 서명하셨습니다.", "info")
        return redirect(url_for("review.detail",
                        inst_id=review.instrument_id, ym=review.year_month))

    chash = review.content_hash()
    meaning = ("정도관리 결과 확인" if role == "qc_manager"
               else "전문의 검토 및 승인")
    sig = Signature(review_id=review.id, user_id=current_user.id, role=role,
                    signer_name=current_user.name, content_hash=chash,
                    meaning=meaning,
                    signature_image=current_user.signature_image)
    db.session.add(sig)

    # 상태 전이
    if role == "qc_manager":
        review.status = "manager_signed"
    elif role == "pathologist":
        review.status = "completed"
    db.session.commit()
    log_audit("SIGN", entity="monthly_review", entity_id=review.id,
              detail=f"{current_user.name}({current_user.role_label}) 전자서명, "
                     f"hash={chash[:12]}…")
    flash(f"{current_user.name} 님의 전자서명이 완료되었습니다.", "success")
    return redirect(url_for("review.detail",
                    inst_id=review.instrument_id, ym=review.year_month))


@bp.route("/<int:review_id>/pdf")
@login_required
def pdf(review_id):
    review = db.get_or_404(MonthlyReview, review_id)
    inst = db.session.get(Instrument, review.instrument_id)
    rows = build_precision_table(review.instrument_id, review.year_month)
    capas = Capa.query.filter_by(review_id=review.id).all()
    signatures = {s.role: s for s in review.signatures}
    integrity_ok = (all(s.content_hash == review.content_hash()
                    for s in review.signatures) if review.signatures else None)
    from ..models import DocumentMeta, QcMaterial
    meta = DocumentMeta.get()
    materials = (QcMaterial.query.filter_by(selected=True)
                 .order_by(QcMaterial.display_order, QcMaterial.id).all())
    assigned_names = assigned_analyte_names(review.instrument_id)
    match = analyte_match_report(review.instrument_id, review.year_month)
    crit_groups = grouped_criteria(rows)
    buf = BytesIO()
    build_pdf(buf, inst, review, rows, capas, signatures, integrity_ok,
              meta=meta, materials=materials,
              assigned_names=assigned_names, match=match,
              crit_groups=crit_groups)
    buf.seek(0)
    log_audit("PDF_EXPORT", entity="monthly_review", entity_id=review.id,
              detail="월간 QC 리포트 PDF 생성")
    fn = f"IQC_{inst.code}_{review.year_month}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True, download_name=fn)
