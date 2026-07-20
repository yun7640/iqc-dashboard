"""검토의견 문구 템플릿 관리 라우트."""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash)
from flask_login import login_required, current_user

from .. import db
from ..models import CommentTemplate
from ..services import log_audit

bp = Blueprint("phrase", __name__, url_prefix="/phrases")

ROLES = [("qc_manager", "정도관리담당"), ("pathologist", "전문의")]


@bp.route("/")
@login_required
def index():
    manager = (CommentTemplate.query.filter_by(role="qc_manager")
               .order_by(CommentTemplate.display_order, CommentTemplate.id).all())
    patho = (CommentTemplate.query.filter_by(role="pathologist")
             .order_by(CommentTemplate.display_order, CommentTemplate.id).all())
    edit_id = request.args.get("edit", type=int)
    edit_item = db.session.get(CommentTemplate, edit_id) if edit_id else None
    return render_template("phrases.html", manager=manager, patho=patho,
                           roles=ROLES, edit_item=edit_item)


@bp.route("/new", methods=["POST"])
@login_required
def new():
    role = request.form.get("role", "qc_manager")
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    order = request.form.get("display_order", type=int) or 0
    if not title or not body:
        flash("제목과 문구 내용을 입력하세요.", "warning")
        return redirect(url_for("phrase.index"))
    t = CommentTemplate(role=role, title=title, body=body, display_order=order,
                        created_by=current_user.name)
    db.session.add(t)
    db.session.commit()
    log_audit("PHRASE_CREATE", entity="comment_template", entity_id=t.id,
              detail=f"[{t.role_label}] {title}")
    flash("검토의견 문구가 등록되었습니다.", "success")
    return redirect(url_for("phrase.index"))


@bp.route("/<int:tid>/edit", methods=["POST"])
@login_required
def edit(tid):
    t = db.get_or_404(CommentTemplate, tid)
    t.role = request.form.get("role", t.role)
    t.title = request.form.get("title", "").strip() or t.title
    t.body = request.form.get("body", "").strip() or t.body
    t.display_order = request.form.get("display_order", type=int) or 0
    db.session.commit()
    log_audit("PHRASE_EDIT", entity="comment_template", entity_id=t.id,
              detail=f"[{t.role_label}] {t.title}")
    flash("문구가 수정되었습니다.", "success")
    return redirect(url_for("phrase.index"))


@bp.route("/<int:tid>/delete", methods=["POST"])
@login_required
def delete(tid):
    t = db.get_or_404(CommentTemplate, tid)
    db.session.delete(t)
    db.session.commit()
    log_audit("PHRASE_DELETE", entity="comment_template", entity_id=tid,
              detail=f"{t.title}")
    flash("문구가 삭제되었습니다.", "info")
    return redirect(url_for("phrase.index"))
