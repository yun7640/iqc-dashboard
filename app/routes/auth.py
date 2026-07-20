"""인증 라우트 (로그인/로그아웃)."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from ..models import User
from ..services import log_audit

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    saved_username = request.cookies.get("saved_username", "")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember_id = request.form.get("remember_id") == "on"
        remember_me = request.form.get("remember_me") == "on"
        user = User.query.filter_by(username=username, active=True).first()
        if user and user.check_password(password):
            # 로그인 유지(remember me): 브라우저를 닫아도 로그인 상태 유지
            login_user(user, remember=remember_me)
            log_audit("LOGIN", entity="user", entity_id=user.id,
                      detail=f"{user.name} 로그인")
            resp = redirect(url_for("dashboard.index"))
            # 아이디 저장: 다음 접속 시 아이디 자동 입력 (1년)
            if remember_id:
                resp.set_cookie("saved_username", username,
                                max_age=60 * 60 * 24 * 365, samesite="Lax")
            else:
                resp.delete_cookie("saved_username")
            return resp
        flash("아이디 또는 비밀번호가 올바르지 않습니다.", "danger")
    # 등록된(활성) 계정 목록 — 아이디·성명·역할만 표시(비밀번호 제외)
    accounts = (User.query.filter_by(active=True)
                .order_by(User.role, User.username).all())
    return render_template("login.html", saved_username=saved_username,
                           remember_id=bool(saved_username), accounts=accounts)


@bp.route("/logout")
@login_required
def logout():
    log_audit("LOGOUT", entity="user", entity_id=current_user.id,
              detail=f"{current_user.name} 로그아웃")
    logout_user()
    return redirect(url_for("auth.login"))
