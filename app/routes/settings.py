"""보고서 설정 — 문서메타(문서번호·제정/개정일시·개정사유) 및 정도관리 현황/물질 관리."""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash)
from flask_login import login_required, current_user

from .. import db
from ..models import (DocumentMeta, QcMaterial, Instrument, Analyte,
                      InstrumentAnalyte, CriteriaGroup)
from ..services import log_audit, assigned_analyte_ids

bp = Blueprint("settings", __name__, url_prefix="/settings")

EVAL_OPTIONS = ["정밀성 검증", "L-J Chart", "정확성 검증", "직선성 검증"]


@bp.route("/")
@login_required
def index():
    meta = DocumentMeta.get()
    materials = QcMaterial.query.order_by(QcMaterial.display_order,
                                          QcMaterial.id).all()
    return render_template("settings.html", meta=meta, materials=materials,
                           eval_options=EVAL_OPTIONS)


@bp.route("/meta", methods=["POST"])
@login_required
def save_meta():
    m = DocumentMeta.get()
    m.institution = request.form.get("institution", "").strip()
    m.department = request.form.get("department", "").strip()
    m.doc_number = request.form.get("doc_number", "").strip()
    m.established_date = request.form.get("established_date", "").strip()
    m.revised_date = request.form.get("revised_date", "").strip()
    m.revision_reason = request.form.get("revision_reason", "").strip()
    m.doc_title = request.form.get("doc_title", "").strip() or m.doc_title
    m.eval_contents = ",".join(request.form.getlist("eval_contents"))
    m.analyte_list = request.form.get("analyte_list", "").strip()
    db.session.commit()
    log_audit("META_SAVE", entity="document_meta", entity_id=1,
              detail=f"문서메타 수정 (문서번호 {m.doc_number})")
    flash("문서 정보 및 정도관리 현황 설정이 저장되었습니다.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/material/new", methods=["POST"])
@login_required
def material_new():
    label = request.form.get("label", "").strip()
    order = request.form.get("display_order", type=int) or 0
    if not label:
        flash("물질명을 입력하세요.", "warning")
        return redirect(url_for("settings.index"))
    db.session.add(QcMaterial(label=label, display_order=order, selected=True))
    db.session.commit()
    log_audit("MATERIAL_ADD", entity="qc_material_item", detail=label)
    flash("정도관리 물질이 추가되었습니다.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/material/toggle", methods=["POST"])
@login_required
def material_toggle():
    """체크박스로 선택된 물질만 selected=True 로 일괄 설정."""
    chosen = set(request.form.getlist("selected"))
    for m in QcMaterial.query.all():
        m.selected = str(m.id) in chosen
    db.session.commit()
    log_audit("MATERIAL_SELECT", entity="qc_material_item",
              detail=f"{len(chosen)}개 물질 선택")
    flash("보고서에 표기할 정도관리 물질 선택이 저장되었습니다.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/material/<int:mid>/delete", methods=["POST"])
@login_required
def material_delete(mid):
    m = db.get_or_404(QcMaterial, mid)
    db.session.delete(m)
    db.session.commit()
    log_audit("MATERIAL_DELETE", entity="qc_material_item", entity_id=mid,
              detail=m.label)
    flash("물질이 삭제되었습니다.", "info")
    return redirect(url_for("settings.index"))


# ---------------------------------------------------------------------------
# 평가장비(기기번호)별 검사항목 배정
# ---------------------------------------------------------------------------
@bp.route("/analytes")
@login_required
def analytes():
    instruments = Instrument.query.order_by(Instrument.code).all()
    inst_id = request.args.get("instrument_id", type=int)
    if not inst_id and instruments:
        inst_id = instruments[0].id
    analytes = Analyte.query.order_by(Analyte.display_order, Analyte.id).all()
    assigned = assigned_analyte_ids(inst_id) if inst_id else None
    # 설정이 없으면(None) 기본 전체 선택으로 표시
    default_all = assigned is None
    assigned_set = set() if assigned is None else assigned
    return render_template("analytes.html", instruments=instruments,
                           inst_id=inst_id, analytes=analytes,
                           assigned_set=assigned_set, default_all=default_all)


@bp.route("/analytes/save", methods=["POST"])
@login_required
def analytes_save():
    inst_id = request.form.get("instrument_id", type=int)
    inst = db.get_or_404(Instrument, inst_id)
    chosen = {int(x) for x in request.form.getlist("analyte")}
    # 모든 검사항목에 대해 배정 레코드를 upsert (active 여부로 관리)
    existing = {ia.analyte_id: ia for ia in
                InstrumentAnalyte.query.filter_by(instrument_id=inst_id).all()}
    for a in Analyte.query.all():
        active = a.id in chosen
        if a.id in existing:
            existing[a.id].active = active
        else:
            db.session.add(InstrumentAnalyte(instrument_id=inst_id,
                           analyte_id=a.id, active=active))
    db.session.commit()
    log_audit("INST_ANALYTE_SAVE", entity="instrument", entity_id=inst_id,
              detail=f"{inst.code} 검사항목 {len(chosen)}개 배정")
    flash(f"{inst.name} 의 평가 검사항목 배정이 저장되었습니다.", "success")
    return redirect(url_for("settings.analytes", instrument_id=inst_id))


# ---------------------------------------------------------------------------
# 항목 특성별 평가기준 그룹 ((Mean)%Diff · (CV)Diff · CV)
# ---------------------------------------------------------------------------
@bp.route("/criteria")
@login_required
def criteria():
    groups = CriteriaGroup.query.order_by(CriteriaGroup.display_order,
                                          CriteriaGroup.id).all()
    analytes = Analyte.query.order_by(Analyte.display_order, Analyte.id).all()
    return render_template("criteria.html", groups=groups, analytes=analytes)


@bp.route("/criteria/group/new", methods=["POST"])
@login_required
def criteria_group_new():
    name = request.form.get("name", "").strip()
    if not name:
        flash("그룹명을 입력하세요.", "warning")
        return redirect(url_for("settings.criteria"))
    g = CriteriaGroup(
        name=name,
        cv_limit=request.form.get("cv_limit", type=float) or 5.0,
        mean_diff_limit=request.form.get("mean_diff_limit", type=float) or 3.0,
        cv_diff_limit=request.form.get("cv_diff_limit", type=float) or 3.0,
        display_order=request.form.get("display_order", type=int) or 0,
        description=request.form.get("description", "").strip())
    db.session.add(g)
    db.session.commit()
    log_audit("CRITERIA_GROUP_NEW", entity="criteria_group", entity_id=g.id,
              detail=f"{name}")
    flash("평가기준 그룹이 추가되었습니다.", "success")
    return redirect(url_for("settings.criteria"))


@bp.route("/criteria/group/<int:gid>/save", methods=["POST"])
@login_required
def criteria_group_save(gid):
    g = db.get_or_404(CriteriaGroup, gid)
    g.name = request.form.get("name", "").strip() or g.name
    g.cv_limit = request.form.get("cv_limit", type=float)
    g.mean_diff_limit = request.form.get("mean_diff_limit", type=float)
    g.cv_diff_limit = request.form.get("cv_diff_limit", type=float)
    g.description = request.form.get("description", "").strip()
    db.session.commit()
    log_audit("CRITERIA_GROUP_SAVE", entity="criteria_group", entity_id=g.id,
              detail=f"{g.name} 기준 수정")
    flash("평가기준이 저장되었습니다.", "success")
    return redirect(url_for("settings.criteria"))


@bp.route("/criteria/group/<int:gid>/delete", methods=["POST"])
@login_required
def criteria_group_delete(gid):
    g = db.get_or_404(CriteriaGroup, gid)
    for a in Analyte.query.filter_by(criteria_group_id=gid).all():
        a.criteria_group_id = None
    db.session.delete(g)
    db.session.commit()
    log_audit("CRITERIA_GROUP_DELETE", entity="criteria_group", entity_id=gid,
              detail=g.name)
    flash("그룹이 삭제되었습니다. 해당 항목은 기본 기준으로 전환됩니다.", "info")
    return redirect(url_for("settings.criteria"))


@bp.route("/criteria/assign", methods=["POST"])
@login_required
def criteria_assign():
    for a in Analyte.query.all():
        val = request.form.get(f"analyte_{a.id}", "")
        a.criteria_group_id = int(val) if val else None
    db.session.commit()
    log_audit("CRITERIA_ASSIGN", detail="검사항목 평가기준 그룹 배정")
    flash("검사항목별 평가기준 그룹 배정이 저장되었습니다.", "success")
    return redirect(url_for("settings.criteria"))
