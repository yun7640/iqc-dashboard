"""마스터 관리 + LIS 파일 import 라우트 (4.1)."""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, current_app)
from flask_login import login_required, current_user

from .. import db
from ..models import Instrument, Analyte, ControlMaterial, Lot, QcTarget
from .. import importers
from ..services import log_audit, recalc_target_month

bp = Blueprint("master", __name__, url_prefix="/master")


@bp.route("/")
@login_required
def index():
    instruments = Instrument.query.all()
    targets = (QcTarget.query.join(QcTarget.analyte)
               .order_by(db.text("analyte.display_order")).all())
    materials = ControlMaterial.query.all()
    return render_template("master.html", instruments=instruments,
                           targets=targets, materials=materials)


@bp.route("/import", methods=["POST"])
@login_required
def import_file():
    kind = request.form.get("kind")
    f = request.files.get("file")
    if not f or not f.filename:
        flash("파일을 선택하세요.", "warning")
        return redirect(url_for("master.index"))
    data = f.read()
    inst_code = request.form.get("instrument_code", "FX8-1")
    try:
        if kind == "precision":
            res = importers.import_precision(data, filename=f.filename,
                                             instrument_code=inst_code)
            msg = f"정밀성 마스터 import: 목표값 {res['targets']}건"
        elif kind == "lj":
            res = importers.import_lj_daily(data, filename=f.filename,
                                            instrument_code=inst_code)
            msg = f"L-J 일별 import: QC결과 {res['results']}건"
            # 판정 재계산
            inst = Instrument.query.filter_by(code=inst_code).first()
            if inst:
                for t in QcTarget.query.filter_by(instrument_id=inst.id).all():
                    recalc_target_month(t.id, "2026-06")
        elif kind == "daily":
            res = importers.import_daily_results(data, filename=f.filename,
                                                 instrument_code=inst_code)
            msg = f"물질별 일일결과 import: {res['results']}건"
        else:
            flash("알 수 없는 파일 유형입니다.", "danger")
            return redirect(url_for("master.index"))
        log_audit("IMPORT", detail=f"{kind}: {f.filename} → {msg}")
        flash(msg, "success")
    except Exception as e:  # noqa: BLE001
        current_app.logger.exception("import error")
        flash(f"import 오류: {e}", "danger")
    return redirect(url_for("master.index"))
