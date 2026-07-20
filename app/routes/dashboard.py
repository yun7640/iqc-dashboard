"""대시보드 홈."""
from flask import Blueprint, render_template
from flask_login import login_required, current_user  # noqa: F401

from ..models import Instrument, MonthlyReview, QcTarget, QcResult, Capa
from ..services import build_precision_table
from .. import db

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    instruments = Instrument.query.all()
    reviews = MonthlyReview.query.order_by(MonthlyReview.year_month.desc()).all()

    # 최신 검토(장비 첫번째, 최신월) 요약 지표
    cards = []
    for inst in instruments:
        latest = (MonthlyReview.query.filter_by(instrument_id=inst.id)
                  .order_by(MonthlyReview.year_month.desc()).first())
        ym = latest.year_month if latest else None
        rows = build_precision_table(inst.id, ym) if ym else []
        total = len(rows)
        flagged = sum(1 for r in rows if not r["pass"])
        rejects = sum(r["n_reject"] for r in rows)
        cards.append({
            "instrument": inst, "ym": ym, "review": latest,
            "total": total, "flagged": flagged, "rejects": rejects,
            "pass_rate": round((total - flagged) / total * 100, 1) if total else 0,
        })

    open_capa = Capa.query.filter_by(resolved=False).count()
    return render_template("dashboard.html", cards=cards, reviews=reviews,
                           open_capa=open_capa)


@bp.route("/guide")
def guide():
    """IQC 대시보드 사용법(공개 페이지). 로그인 없이도 열람 가능."""
    return render_template("guide.html")
