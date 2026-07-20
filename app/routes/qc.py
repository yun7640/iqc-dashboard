"""QC 입력 · Levey-Jennings 차트 · 멀티룰 판정 라우트 (4.2)."""
from datetime import datetime, date

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify)
from flask_login import login_required

from .. import db
from ..models import Instrument, Analyte, QcTarget, QcResult
from ..services import recalc_target_month, month_stats, log_audit
from ..westgard import z_of, RULE_INFO

bp = Blueprint("qc", __name__, url_prefix="/qc")


@bp.route("/")
@login_required
def index():
    instruments = Instrument.query.all()
    inst_id = request.args.get("instrument_id", type=int)
    if not inst_id and instruments:
        inst_id = instruments[0].id
    ym = request.args.get("ym", "2026-06")
    targets = []
    if inst_id:
        targets = (QcTarget.query.filter_by(instrument_id=inst_id)
                   .join(QcTarget.analyte)
                   .order_by(db.text("analyte.display_order")).all())
    return render_template("qc_list.html", instruments=instruments,
                           inst_id=inst_id, ym=ym, targets=targets)


@bp.route("/chart/<int:target_id>")
@login_required
def chart(target_id):
    ym = request.args.get("ym", "2026-06")
    target = db.get_or_404(QcTarget, target_id)
    return render_template("qc_chart.html", target=target, ym=ym,
                           rule_info=RULE_INFO)


@bp.route("/api/series/<int:target_id>")
@login_required
def api_series(target_id):
    """L-J 차트용 시계열 JSON."""
    ym = request.args.get("ym", "2026-06")
    target = db.get_or_404(QcTarget, target_id)
    recalc_target_month(target_id, ym)
    y, m = ym.split("-")
    results = (QcResult.query.filter_by(target_id=target_id)
               .filter(db.extract("year", QcResult.result_date) == int(y))
               .filter(db.extract("month", QcResult.result_date) == int(m))
               .order_by(QcResult.result_date, QcResult.run_seq).all())
    points = [{
        "date": r.result_date.strftime("%m-%d"),
        "value": r.value, "z": r.z_score, "status": r.status,
        "rules": r.rules or "",
    } for r in results]
    st = month_stats(results)
    return jsonify({
        "analyte": target.analyte.name, "level": target.level,
        "mean": round(target.center_mean, 2), "sd": round(target.center_sd, 3),
        "assigned_mean": target.target_mean, "assigned_sd": target.target_sd,
        "cv": st["cv"], "n": st["n"],
        "points": points,
    })


@bp.route("/input", methods=["GET", "POST"])
@login_required
def input_result():
    """일일 QC 수기 입력."""
    instruments = Instrument.query.all()
    if request.method == "POST":
        target_id = request.form.get("target_id", type=int)
        rdate = request.form.get("result_date")
        value = request.form.get("value", type=float)
        target = db.session.get(QcTarget, target_id)
        if not target or value is None:
            flash("입력값을 확인하세요.", "warning")
            return redirect(url_for("qc.input_result"))
        d = datetime.strptime(rdate, "%Y-%m-%d").date()
        seq = QcResult.query.filter_by(target_id=target_id,
                                       result_date=d).count() + 1
        db.session.add(QcResult(target_id=target_id, result_date=d,
                                run_seq=seq, value=value))
        db.session.commit()
        ym = d.strftime("%Y-%m")
        recalc_target_month(target_id, ym)
        log_audit("QC_INPUT", entity="qc_target", entity_id=target_id,
                  detail=f"{target.analyte.name} {target.level} {rdate}={value}")
        flash("QC 결과가 입력되었습니다.", "success")
        return redirect(url_for("qc.chart", target_id=target_id, ym=ym))

    inst_id = request.args.get("instrument_id", type=int) or (
        instruments[0].id if instruments else None)
    targets = (QcTarget.query.filter_by(instrument_id=inst_id)
               .join(QcTarget.analyte)
               .order_by(db.text("analyte.display_order")).all()) if inst_id else []
    return render_template("qc_input.html", instruments=instruments,
                           inst_id=inst_id, targets=targets,
                           today=date.today().isoformat())
