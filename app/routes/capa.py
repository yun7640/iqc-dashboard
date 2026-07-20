"""시정조치(CAPA) 라우트 (4.4)."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from .. import db
from ..models import Capa, MonthlyReview, QcResult, QcTarget
from ..services import log_audit

bp = Blueprint("capa", __name__, url_prefix="/capa")


@bp.route("/")
@login_required
def index():
    capas = Capa.query.order_by(Capa.created_at.desc()).all()
    return render_template("capa_list.html", capas=capas)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    review_id = request.args.get("review_id", type=int)
    qc_result_id = request.args.get("qc_result_id", type=int)
    if request.method == "POST":
        capa = Capa(
            review_id=request.form.get("review_id", type=int),
            qc_result_id=request.form.get("qc_result_id", type=int),
            analyte_name=request.form.get("analyte_name", ""),
            event_summary=request.form.get("event_summary", ""),
            cause=request.form.get("cause", ""),
            action=request.form.get("action", ""),
            prevention=request.form.get("prevention", ""),
            created_by=current_user.name,
        )
        db.session.add(capa)
        db.session.commit()
        log_audit("CAPA_CREATE", entity="capa", entity_id=capa.id,
                  detail=f"{capa.analyte_name} 시정조치 등록")
        flash("시정조치가 등록되었습니다.", "success")
        rv = db.session.get(MonthlyReview, capa.review_id) if capa.review_id else None
        if rv:
            return redirect(url_for("review.detail",
                            inst_id=rv.instrument_id, ym=rv.year_month))
        return redirect(url_for("capa.index"))

    reviews = MonthlyReview.query.all()
    prefill = {}
    if qc_result_id:
        r = db.session.get(QcResult, qc_result_id)
        if r:
            t = r.target
            prefill = {
                "analyte_name": t.analyte.name,
                "event_summary": f"{t.analyte.name} {t.level} "
                                 f"{r.rules} 위반 ({r.result_date})",
            }
    return render_template("capa_form.html", reviews=reviews,
                           review_id=review_id, qc_result_id=qc_result_id,
                           prefill=prefill)


@bp.route("/<int:capa_id>/resolve", methods=["POST"])
@login_required
def resolve(capa_id):
    capa = db.get_or_404(Capa, capa_id)
    capa.resolved = True
    db.session.commit()
    log_audit("CAPA_RESOLVE", entity="capa", entity_id=capa.id,
              detail=f"{capa.analyte_name} 시정조치 완료 처리")
    flash("시정조치가 완료 처리되었습니다.", "success")
    return redirect(url_for("capa.index"))
