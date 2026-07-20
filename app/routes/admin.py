"""관리자 기능 — 사용자 계정 관리, 평가장비 및 장비별 담당자·전문의 지정."""
from functools import wraps

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort)
from flask_login import login_required, current_user

from .. import db
from ..models import User, Instrument, Signature
from ..services import log_audit

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------- 사용자 관리
@bp.route("/users")
@login_required
@admin_required
def users():
    users = User.query.order_by(User.role, User.username).all()
    return render_template("users.html", users=users)


@bp.route("/users/new", methods=["POST"])
@login_required
@admin_required
def user_new():
    username = request.form.get("username", "").strip()
    name = request.form.get("name", "").strip()
    if not username or not name:
        flash("아이디와 성명을 입력하세요.", "warning")
        return redirect(url_for("admin.users"))
    if User.query.filter_by(username=username).first():
        flash("이미 존재하는 아이디입니다.", "danger")
        return redirect(url_for("admin.users"))
    u = User(username=username, name=name,
             title=request.form.get("title", "").strip(),
             role=request.form.get("role", "qc_manager"))
    u.set_password(request.form.get("password") or "changeme123")
    db.session.add(u)
    db.session.commit()
    log_audit("USER_NEW", entity="user", entity_id=u.id, detail=f"{name}({username})")
    flash(f"사용자 '{name}' 이(가) 추가되었습니다. 초기 비밀번호를 안내하세요.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/edit", methods=["POST"])
@login_required
@admin_required
def user_edit(uid):
    u = db.get_or_404(User, uid)
    u.name = request.form.get("name", "").strip() or u.name
    u.title = request.form.get("title", "").strip()
    u.role = request.form.get("role", u.role)
    u.active = request.form.get("active") == "on"
    db.session.commit()
    log_audit("USER_EDIT", entity="user", entity_id=u.id, detail=f"{u.name} 정보 수정")
    flash("사용자 정보가 수정되었습니다.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/delete", methods=["POST"])
@login_required
@admin_required
def user_delete(uid):
    u = db.get_or_404(User, uid)
    # 본인 계정 삭제 불가
    if u.id == current_user.id:
        flash("본인 계정은 삭제할 수 없습니다.", "warning")
        return redirect(url_for("admin.users"))
    # 마지막 관리자 삭제 방지
    if u.role == "admin" and User.query.filter_by(role="admin").count() <= 1:
        flash("마지막 관리자 계정은 삭제할 수 없습니다.", "warning")
        return redirect(url_for("admin.users"))
    # 전자서명 기록이 있으면 삭제 불가(무결성 보존) → 비활성화 권고
    if Signature.query.filter_by(user_id=u.id).first():
        flash("전자서명 기록이 있는 계정은 삭제할 수 없습니다(인증·감사 무결성 보존). "
              "대신 '활성' 체크를 해제하여 비활성화하세요.", "danger")
        return redirect(url_for("admin.users"))
    # 장비 지정에서 해제 후 삭제
    for inst in Instrument.query.filter_by(manager_id=u.id).all():
        inst.manager_id = None
    for inst in Instrument.query.filter_by(pathologist_id=u.id).all():
        inst.pathologist_id = None
    name = u.name
    db.session.delete(u)
    db.session.commit()
    log_audit("USER_DELETE", entity="user", entity_id=uid, detail=f"{name}({u.username}) 삭제")
    flash(f"사용자 '{name}' 계정이 삭제되었습니다.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/password", methods=["POST"])
@login_required
@admin_required
def user_password(uid):
    u = db.get_or_404(User, uid)
    pw = request.form.get("password", "")
    if len(pw) < 4:
        flash("비밀번호는 4자 이상 입력하세요.", "warning")
        return redirect(url_for("admin.users"))
    u.set_password(pw)
    db.session.commit()
    log_audit("USER_PW_RESET", entity="user", entity_id=u.id,
              detail=f"{u.name} 비밀번호 재설정")
    flash(f"'{u.name}' 비밀번호가 재설정되었습니다.", "success")
    return redirect(url_for("admin.users"))


# ---------------------------------------------------- 장비 · 담당자/전문의 지정
@bp.route("/instruments")
@login_required
@admin_required
def instruments():
    instruments = Instrument.query.order_by(Instrument.code).all()
    managers = User.query.filter_by(role="qc_manager", active=True).all()
    pathologists = User.query.filter_by(role="pathologist", active=True).all()
    return render_template("instruments.html", instruments=instruments,
                           managers=managers, pathologists=pathologists)


@bp.route("/instruments/new", methods=["POST"])
@login_required
@admin_required
def instrument_new():
    code = request.form.get("code", "").strip()
    name = request.form.get("name", "").strip()
    if not code or not name:
        flash("장비코드와 장비명을 입력하세요.", "warning")
        return redirect(url_for("admin.instruments"))
    if Instrument.query.filter_by(code=code).first():
        flash("이미 존재하는 장비코드입니다.", "danger")
        return redirect(url_for("admin.instruments"))
    db.session.add(Instrument(code=code, name=name))
    db.session.commit()
    log_audit("INSTRUMENT_NEW", detail=f"{code} {name}")
    flash("평가장비가 추가되었습니다.", "success")
    return redirect(url_for("admin.instruments"))


@bp.route("/instruments/<int:iid>/save", methods=["POST"])
@login_required
@admin_required
def instrument_save(iid):
    inst = db.get_or_404(Instrument, iid)
    inst.name = request.form.get("name", "").strip() or inst.name
    mid = request.form.get("manager_id", type=int)
    pid = request.form.get("pathologist_id", type=int)
    old = (inst.manager_id, inst.pathologist_id)
    inst.manager_id = mid or None
    inst.pathologist_id = pid or None
    db.session.commit()
    mgr = inst.manager.name if inst.manager else "-"
    pat = inst.pathologist.name if inst.pathologist else "-"
    log_audit("INSTRUMENT_STAFF", entity="instrument", entity_id=inst.id,
              detail=f"{inst.code} 담당자={mgr}, 전문의={pat} (이전 {old})")
    flash(f"{inst.name} 의 담당자·전문의 지정이 저장되었습니다.", "success")
    return redirect(url_for("admin.instruments"))
