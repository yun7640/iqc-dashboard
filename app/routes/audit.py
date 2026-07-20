"""감사추적 로그 조회 라우트 (4.3)."""
from flask import Blueprint, render_template, request
from flask_login import login_required

from ..models import AuditLog

bp = Blueprint("audit", __name__, url_prefix="/audit")


@bp.route("/")
@login_required
def index():
    action = request.args.get("action", "")
    q = AuditLog.query
    if action:
        q = q.filter_by(action=action)
    logs = q.order_by(AuditLog.at.desc()).limit(500).all()
    actions = [a[0] for a in
               AuditLog.query.with_entities(AuditLog.action).distinct().all()]
    return render_template("audit.html", logs=logs, actions=actions,
                           sel_action=action)
