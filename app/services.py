"""도메인 서비스 로직.

정밀성 통계 산출, 멀티룰 재판정, 검토 페이로드 구성, 감사추적 기록 등
라우트에서 공통으로 사용하는 함수를 모은다.
"""
from datetime import datetime
from statistics import mean, stdev
from flask import request
from flask_login import current_user

from . import db
from .models import (QcResult, QcTarget, AuditLog, MonthlyReview, Signature,
                     Capa, PrecisionSummary, InstrumentAnalyte, Analyte)
from .westgard import evaluate_series, z_of, RULE_INFO
from config import Config


# ---------------------------------------------------------------------------
# 감사추적
# ---------------------------------------------------------------------------
def log_audit(action, entity=None, entity_id=None, detail=None):
    """감사추적 로그 기록. current_user 가 있으면 사용자 정보를 함께 저장."""
    try:
        uid = current_user.id if current_user.is_authenticated else None
        uname = current_user.name if current_user.is_authenticated else "-"
    except Exception:
        uid, uname = None, "-"
    entry = AuditLog(
        user_id=uid, user_name=uname, action=action,
        entity=entity, entity_id=entity_id, detail=detail,
        ip=request.remote_addr if request else None,
    )
    db.session.add(entry)
    db.session.commit()


# ---------------------------------------------------------------------------
# 정밀성 / 멀티룰 판정
# ---------------------------------------------------------------------------
def cv_limit_for(target):
    """검사항목 저농도 여부에 따른 CV 허용기준."""
    if target.analyte and target.analyte.low_concentration:
        return Config.CV_LIMIT_LOW
    return Config.CV_LIMIT


def limits_for_analyte(analyte):
    """검사항목의 특성 그룹 기준(CV / (Mean)%Diff / (CV)Diff).

    항목이 평가기준 그룹에 배정돼 있으면 그룹 값을, 없으면 전역 기본값
    (저농도 항목은 CV 10%)을 사용한다.
    """
    if analyte is None:
        return Config.CV_LIMIT, Config.MEAN_DIFF_LIMIT, Config.CV_DIFF_LIMIT
    g = analyte.criteria_group
    if g:
        return g.cv_limit, g.mean_diff_limit, g.cv_diff_limit
    cvlim = Config.CV_LIMIT_LOW if analyte.low_concentration else Config.CV_LIMIT
    return cvlim, Config.MEAN_DIFF_LIMIT, Config.CV_DIFF_LIMIT


def recalc_target_month(target_id, year_month):
    """대상 target 의 해당 월 QC 결과에 z-score·멀티룰을 재계산·저장."""
    target = db.session.get(QcTarget, target_id)
    if not target:
        return
    y, m = year_month.split("-")
    results = (
        QcResult.query.filter_by(target_id=target_id)
        .filter(db.extract("year", QcResult.result_date) == int(y))
        .filter(db.extract("month", QcResult.result_date) == int(m))
        .order_by(QcResult.result_date, QcResult.run_seq)
        .all()
    )
    zs = [z_of(r.value, target.center_mean, target.center_sd) for r in results]
    evals = evaluate_series(zs)
    for r, e in zip(results, evals):
        r.z_score = round(e.z, 3)
        r.status = e.status
        r.rules = ",".join(e.violated)
    db.session.commit()
    return results, evals


def month_stats(results):
    """해당 월 결과값의 평균·SD·CV 산출."""
    vals = [r.value for r in results]
    if len(vals) < 2:
        m = vals[0] if vals else 0
        return {"n": len(vals), "mean": round(m, 2), "sd": 0.0, "cv": 0.0}
    m = mean(vals)
    s = stdev(vals)
    cv = (s / m * 100) if m else 0
    return {"n": len(vals), "mean": round(m, 2), "sd": round(s, 2), "cv": round(cv, 2)}


def prev_month(year_month):
    y, m = map(int, year_month.split("-"))
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y:04d}-{m:02d}"


def _daily_rule_counts(target_id, year_month):
    """해당 target·월의 일별 멀티룰 reject/warn 건수."""
    y, m = year_month.split("-")
    results = (
        QcResult.query.filter_by(target_id=target_id)
        .filter(db.extract("year", QcResult.result_date) == int(y))
        .filter(db.extract("month", QcResult.result_date) == int(m))
        .all()
    )
    n_reject = sum(1 for r in results if r.status == "reject")
    n_warn = sum(1 for r in results if r.status == "warning")
    return len(results), n_reject, n_warn


def can_act_as(instrument, user, role):
    """장비별 지정 담당자/전문의만 해당 역할로 검토의견 작성·전자서명 가능.

    - admin 은 항상 허용
    - 장비에 담당자/전문의가 지정돼 있으면 '그 사용자'만 허용
    - 지정이 없으면(None) 해당 역할 사용자 누구나 허용(하위호환)
    """
    if user is None:
        return False
    if user.role == "admin":
        return True
    if role == "qc_manager":
        if user.role != "qc_manager":
            return False
        return instrument.manager_id in (None, user.id)
    if role == "pathologist":
        if user.role != "pathologist":
            return False
        return instrument.pathologist_id in (None, user.id)
    return False


def assigned_analyte_ids(instrument_id):
    """장비에 배정된 검사항목 id 집합. 설정이 전혀 없으면 None(=전체 대상)."""
    any_row = InstrumentAnalyte.query.filter_by(instrument_id=instrument_id).first()
    if not any_row:
        return None
    rows = InstrumentAnalyte.query.filter_by(
        instrument_id=instrument_id, active=True).all()
    return {r.analyte_id for r in rows}


def assigned_analyte_names(instrument_id):
    """장비에 배정된 검사항목명 리스트(표시순)."""
    ids = assigned_analyte_ids(instrument_id)
    q = Analyte.query
    if ids is not None:
        if not ids:
            return []
        q = q.filter(Analyte.id.in_(ids))
    return [a.name for a in q.order_by(Analyte.display_order, Analyte.id).all()]


def analyte_match_report(instrument_id, year_month):
    """LIS 다운로드 결과 항목 vs 장비별 배정 검사항목 매칭 점검.

    - missing   : 배정되었으나 LIS 결과가 없는 항목 (결과 누락)
    - unexpected: LIS 결과는 있으나 장비에 배정되지 않은 항목 (미설정 항목)
    """
    assigned = assigned_analyte_ids(instrument_id)
    # LIS 결과가 존재하는 항목(해당 월 정밀성 요약 기준)
    imported = {
        ps.analyte_id for ps in PrecisionSummary.query.filter_by(
            instrument_id=instrument_id, year_month=year_month).all()
    }
    if assigned is None:
        return {"configured": False, "missing": [], "unexpected": [], "ok": True}

    def names(id_set):
        if not id_set:
            return []
        return [a.name for a in Analyte.query.filter(Analyte.id.in_(id_set))
                .order_by(Analyte.display_order, Analyte.id).all()]

    missing = names(assigned - imported)
    unexpected = names(imported - assigned)
    return {
        "configured": True,
        "missing": missing,
        "unexpected": unexpected,
        "ok": not missing and not unexpected,
    }


def build_precision_table(instrument_id, year_month):
    """장비·월별 정밀성 종합검토 테이블 생성.

    정밀성 통계는 LIS 원본(PrecisionSummary)을 사용하고, 멀티룰 위반 건수는
    일별 QcResult 판정에서 집계한다. LMB05 [표3] 평가기준으로 적합/확인 판정.
    분석 평가는 장비에 배정된 검사항목에 대해서만 진행한다.
    """
    assigned = assigned_analyte_ids(instrument_id)
    summaries = (
        PrecisionSummary.query.filter_by(
            instrument_id=instrument_id, year_month=year_month)
        .join(PrecisionSummary.analyte)
        .order_by(db.text("analyte.display_order"))
        .all()
    )
    rows = []
    for ps in summaries:
        # 장비에 배정된 검사항목만 평가 (설정이 있을 때)
        if assigned is not None and ps.analyte_id not in assigned:
            continue
        target = QcTarget.query.filter_by(
            instrument_id=instrument_id, analyte_id=ps.analyte_id,
            level=ps.level).first()
        # 항목 특성 그룹 기준 적용
        cvlim, meanlim, cvdifflim = limits_for_analyte(ps.analyte)
        grp = ps.analyte.criteria_group.name if (ps.analyte and ps.analyte.criteria_group) else ""

        flags = []
        if ps.cur_cv is not None and ps.cur_cv > cvlim:
            flags.append(f"CV {ps.cur_cv}% > {cvlim}%")
        if ps.mean_pct_diff is not None and abs(ps.mean_pct_diff) > meanlim:
            flags.append(f"(Mean)%Diff {ps.mean_pct_diff}% 초과")
        if ps.cv_diff is not None and abs(ps.cv_diff) > cvdifflim:
            flags.append(f"(CV)Diff {ps.cv_diff} 초과")

        n, n_reject, n_warn = (0, 0, 0)
        if target:
            n, n_reject, n_warn = _daily_rule_counts(target.id, year_month)

        rows.append({
            "target": target,
            "analyte": ps.analyte.name if ps.analyte else "",
            "level": ps.level,
            "lot_no": ps.lot.lot_no if ps.lot else "",
            "target_mean": ps.target_mean or 0,
            "target_sd": ps.target_sd or 0,
            "prev_mean": ps.prev_mean,
            "cur_mean": ps.cur_mean or 0,
            "cur_sd": ps.cur_sd or 0,
            "prev_cv": ps.prev_cv,
            "cur_cv": ps.cur_cv or 0,
            "cv_limit": cvlim,
            "mean_diff_limit": meanlim,
            "cv_diff_limit": cvdifflim,
            "criteria_group": grp,
            "mean_pct_diff": ps.mean_pct_diff,
            "cv_diff": ps.cv_diff,
            "n": n,
            "n_reject": n_reject,
            "n_warn": n_warn,
            "flags": flags,
            "pass": len(flags) == 0 and n_reject == 0,
        })
    return rows


def grouped_criteria(rows):
    """정밀성 평가기준을 항목 특성(그룹)별로 묶어 표시용 구조로 반환.

    같은 기준(그룹명·CV·%Diff·CVDiff)을 가진 검사항목을 하나로 묶는다.
    """
    from collections import OrderedDict
    groups = OrderedDict()
    for r in rows:
        key = (r.get("criteria_group") or "기본 기준",
               r["cv_limit"], r["mean_diff_limit"], r["cv_diff_limit"])
        g = groups.setdefault(key, {
            "name": key[0], "cv_limit": key[1],
            "mean_diff_limit": key[2], "cv_diff_limit": key[3], "analytes": []})
        if r["analyte"] not in g["analytes"]:
            g["analytes"].append(r["analyte"])
    return list(groups.values())


def build_review_payload(review: MonthlyReview):
    """무결성 해시 대상 페이로드.

    서명이 귀속(attest)되는 대상은 '검토한 QC 데이터셋'이다. 담당·전문의가
    동일한 정밀성 데이터에 서명하며, 서명 이후 QC 데이터가 변경되면 해시가
    달라져 무결성 훼손을 탐지한다. 자유서술 검토의견은 서명자별로 시점이
    다르므로 데이터 무결성 해시에서는 제외한다(감사추적 로그로 별도 관리).
    """
    rows = build_precision_table(review.instrument_id, review.year_month)
    slim = [
        {
            "analyte": r["analyte"], "level": r["level"], "lot": r["lot_no"],
            "target_mean": r["target_mean"], "target_sd": r["target_sd"],
            "cur_mean": r["cur_mean"], "cur_cv": r["cur_cv"],
            "mean_pct_diff": r["mean_pct_diff"], "cv_diff": r["cv_diff"],
            "n_reject": r["n_reject"], "pass": r["pass"],
        }
        for r in rows
    ]
    return {
        "instrument_id": review.instrument_id,
        "year_month": review.year_month,
        "rows": slim,
    }
