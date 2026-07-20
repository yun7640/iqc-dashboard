"""데모/합성 시드 데이터 적재.

첨부된 FX8 1호기 실제 LIS export(2026-06 정밀성, Glucose L-J 일별)를
기준으로 마스터·목표값을 등록하고, 정밀성 통계와 일치하도록 일별 QC
시계열을 재구성한다.

  * Glucose level1/level3 : 실제 L-J 일별 export 값 그대로 적재
  * 그 외 항목            : 정밀성 export 의 당월 Mean/SD 및 전월 Mean/CV 에
                            맞춰 재현(합성)한 일별 시계열
  * 환자 식별정보는 일절 포함하지 않으며 관리물질 QC 데이터만 사용

배포용 완전 합성이 필요하면 SEED_SYNTHETIC_ONLY=1 로 실행한다.
"""
import os
import random
import csv
from datetime import date, datetime, timedelta

from . import db
from .models import (User, Instrument, Analyte, QcTarget, QcResult,
                     MonthlyReview, Capa, CommentTemplate, DocumentMeta,
                     QcMaterial, InstrumentAnalyte, CriteriaGroup)
from . import importers
from . import services

# LIS(검사정보시스템) 실제 다운로드 파일명과 매핑
#   월통계(정밀성)  : 202606_일반화학_내부QC월통계_다운.xls
#   L-J 일별        : 202606_Glucose_QC_data_다운.xls
#   당일 물질별결과 : 20260709_일반화학_내부QC결과_다운.xls
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SAMPLE = os.path.join(BASE, "sample_data")
# 기본 파일명(참고) — 실제 식별은 파일 내용(헤더)으로 수행한다.
PRECISION_CSV = os.path.join(SAMPLE, "202606_일반화학_내부QC월통계_다운.xls")
LJ_CSV = os.path.join(SAMPLE, "202606_Glucose_QC_data_다운.xls")

CUR_YM = "2026-06"
PREV_YM = "2026-05"


def _classify_samples():
    """sample_data 폴더의 파일을 '파일명이 아닌 내용(헤더)'으로 식별한다.

    한글 파일명이 압축 해제 환경(예: Windows 탐색기)에서 깨지더라도
    시드가 정상 동작하도록, 헤더 시그니처로 정밀성/L-J 파일을 분류한다.
    """
    import glob
    prec_path = lj_path = None
    candidates = []
    for ext in ("*.xls", "*.xlsx", "*.csv"):
        candidates.extend(glob.glob(os.path.join(SAMPLE, ext)))
    for p in sorted(candidates):
        try:
            rows = importers._read_rows(p, filename=p)
        except Exception:
            continue
        if not rows:
            continue
        header = " ".join(str(c).strip() for c in rows[0])
        # 정밀성(월통계): 'Target Mean' + 'LOTNO'
        if prec_path is None and "Target Mean" in header and "LOTNO" in header:
            prec_path = p
        # L-J 일별: '장비명' 또는 '실제Mean'
        elif lj_path is None and ("장비명" in header or "실제Mean" in header):
            lj_path = p
    # 헤더로 못 찾으면 기본 파일명으로 폴백
    if prec_path is None and os.path.exists(PRECISION_CSV):
        prec_path = PRECISION_CSV
    if lj_path is None and os.path.exists(LJ_CSV):
        lj_path = LJ_CSV
    return prec_path, lj_path


def _weekday_dates(year, month, n):
    """해당 월의 평일 앞에서부터 n개 날짜 반환."""
    out = []
    d = date(year, month, 1)
    while len(out) < n:
        if d.weekday() < 5:  # 월~금
            out.append(d)
        d += timedelta(days=1)
        if d.month != month:
            break
    return out


def _synth_series(mean, sd, n, seed):
    """평균·SD 목표에 근사하는 n개 정규분포 표본(관리물질 재현)."""
    if not mean:
        return []
    rng = random.Random(seed)
    sd = sd if sd and sd > 0 else max(abs(mean) * 0.01, 0.01)
    raw = [rng.gauss(mean, sd) for _ in range(n)]
    # 목표 mean/sd 로 표준화 보정
    cur_m = sum(raw) / n
    dev = [(x - cur_m) for x in raw]
    var = sum(d * d for d in dev) / (n - 1) if n > 1 else 0
    cur_sd = var ** 0.5 or 1
    scale = sd / cur_sd
    adj = [mean + d * scale for d in dev]
    # 소수 자리 정리 (검사항목 특성 반영)
    ndp = 2 if abs(mean) < 10 else 1
    return [round(x, ndp) for x in adj]


def run_seed(synthetic_only=None):
    if synthetic_only is None:
        synthetic_only = os.environ.get("SEED_SYNTHETIC_ONLY") == "1"

    # ------------------------------------------------------------ 사용자
    def _load_sign(fname):
        """샘플 서명 PNG 를 data URI 로 로드(데모용). 파일 없으면 None."""
        import base64
        p = os.path.join(BASE, "app", "static", "samples", fname)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                return "data:image/png;base64," + base64.b64encode(fh.read()).decode()
        return None

    if not User.query.first():
        admin = User(username="admin", name="관리자", title="시스템관리자", role="admin")
        admin.set_password("admin123")
        mgr = User(username="qc", name="최_파트", title="임상병리사", role="qc_manager")
        mgr.set_password("qc123")
        mgr.signature_image = _load_sign("sample_sign_qc.png")
        path = User(username="dr", name="윤_전문", title="진단검사의학과 전문의",
                    role="pathologist")
        path.set_password("dr123")
        path.signature_image = _load_sign("sample_sign_dr.png")
        db.session.add_all([admin, mgr, path])
        db.session.commit()

    # ------------------------------------------------------------ 샘플 파일 식별
    prec_path, lj_path = _classify_samples()
    if not prec_path:
        raise FileNotFoundError(
            "sample_data 폴더에서 정밀성(월통계) 파일을 찾지 못했습니다. "
            "'Target Mean'·'LOTNO' 헤더를 가진 .xls/.csv 파일이 있는지 확인하세요.")

    # ------------------------------------------------------------ 마스터/목표값
    importers.import_precision(prec_path, filename=prec_path,
                               instrument_code="FX8-1",
                               instrument_name="TBA FX8 #1",
                               year_month=CUR_YM)
    inst = Instrument.query.filter_by(code="FX8-1").first()

    # ------------------------------------------------------------ 합성 일별 시계열
    # 정밀성 파일에서 당월/전월 통계 파라미터를 읽어 시계열 재현
    rows = importers._read_rows(prec_path, filename=prec_path)
    cur_dates = _weekday_dates(2026, 6, 22)
    prev_dates = _weekday_dates(2026, 5, 22)

    for i, row in enumerate(rows[1:], start=1):
        if len(row) < 8 or not row[1].strip():
            continue
        lot_no, analyte_name, level = row[0].strip(), row[1].strip(), row[2].strip()
        def ff(x):
            try:
                return float(str(x).replace(",", ""))
            except ValueError:
                return None
        prev_mean, cur_mean, cur_sd = ff(row[5]), ff(row[6]), ff(row[7])
        prev_cv = ff(row[8])
        analyte = Analyte.query.filter_by(name=analyte_name).first()
        if not analyte:
            continue
        target = QcTarget.query.filter_by(
            instrument_id=inst.id, analyte_id=analyte.id, level=level).first()
        if not target:
            continue

        # 이미 데이터가 있으면(예: 실데이터 import 예정) 건너뜀
        has_data = QcResult.query.filter_by(target_id=target.id).first()
        if has_data:
            continue

        # L-J 일별 시계열 재현: 배정평균 중심, spread = 배정SD의 60%
        # (관리물질이 관리상태(in-control)일 때의 전형적 분포를 재현)
        # 운영중심선(oper) = 배정값. 정밀성 요약은 PrecisionSummary(실측)로 별도 보존.
        target.oper_mean = target.target_mean
        target.oper_sd = target.target_sd
        spread = (target.target_sd or 0) * 0.6
        vals = _synth_series(target.target_mean, spread, len(cur_dates),
                             seed=1000 + i)
        for d, v in zip(cur_dates, vals):
            db.session.add(QcResult(target_id=target.id, result_date=d,
                                    run_seq=1, value=v))
    db.session.commit()

    # ------------------------------------------------------------ 실제 Glucose L-J
    if not synthetic_only and lj_path and os.path.exists(lj_path):
        # 기존 합성 Glucose 6월 데이터 삭제 후 실데이터로 대체
        glu = Analyte.query.filter_by(name="Glucose").first()
        if glu:
            gtargets = QcTarget.query.filter_by(
                instrument_id=inst.id, analyte_id=glu.id).all()
            for gt in gtargets:
                QcResult.query.filter(
                    QcResult.target_id == gt.id,
                    db.extract("year", QcResult.result_date) == 2026,
                    db.extract("month", QcResult.result_date) == 6,
                ).delete(synchronize_session=False)
            db.session.commit()
            importers.import_lj_daily(lj_path, filename=lj_path,
                                      instrument_code="FX8-1")
            # 실측 Glucose: 운영중심선 = 당월 관측평균, 관리 SD = 배정 SD
            from statistics import mean as _m
            for gt in gtargets:
                vals = [r.value for r in QcResult.query.filter_by(
                        target_id=gt.id).filter(
                        db.extract("month", QcResult.result_date) == 6).all()]
                if vals:
                    gt.oper_mean = round(_m(vals), 3)
                    gt.oper_sd = gt.target_sd
            db.session.commit()

    # ------------------------------------------------------------ 데모 이상치 + CAPA
    # 멀티룰/시정조치 흐름 시연을 위해 CK level3 에 1건의 1_3s 이탈을 주입
    demo_analyte = Analyte.query.filter_by(name="CK").first()
    if demo_analyte:
        t = QcTarget.query.filter_by(
            instrument_id=inst.id, analyte_id=demo_analyte.id,
            level="level3").first()
        if t:
            # 6월 중순 한 지점을 +3.4SD 지점으로 설정
            excursion_date = date(2026, 6, 17)
            r = (QcResult.query.filter_by(target_id=t.id,
                 result_date=excursion_date).first())
            outlier_val = round(t.target_mean + 3.4 * t.target_sd, 1)
            if r:
                r.value = outlier_val
                r.action = "[데모] 시연용 가상 이탈"
            else:
                db.session.add(QcResult(target_id=t.id,
                               result_date=excursion_date, run_seq=1,
                               value=outlier_val,
                               action="[데모] 시연용 가상 이탈"))
            db.session.commit()

    # ------------------------------------------------------------ 재판정(z/멀티룰)
    for t in QcTarget.query.filter_by(instrument_id=inst.id).all():
        services.recalc_target_month(t.id, CUR_YM)

    # ------------------------------------------------------------ 월별 검토 레코드
    review = MonthlyReview.query.filter_by(
        instrument_id=inst.id, year_month=CUR_YM).first()
    if not review:
        review = MonthlyReview(instrument_id=inst.id, year_month=CUR_YM,
                               status="draft")
        db.session.add(review)
        db.session.commit()

    # 데모 CAPA (CK 이탈 연계)
    if demo_analyte and not Capa.query.first():
        ck_reject = (QcResult.query.join(QcTarget)
                     .filter(QcTarget.analyte_id == demo_analyte.id,
                             QcResult.status == "reject").first())
        capa = Capa(
            review_id=review.id,
            qc_result_id=ck_reject.id if ck_reject else None,
            analyte_name="CK",
            event_summary="[데모] CK level3 1_3s 위반 (2026-06-17)",
            cause="[데모 예시] 시약 카트리지 교체 직후 캘리브레이션 편차 추정 "
                  "— 실제 LIS 데이터가 아니라 워크플로 시연을 위한 가상 이벤트입니다.",
            action="재검 실시, Q.C after ReCAL 수행, new bottle 로 ReRUN",
            prevention="시약 교체 시 QC 재확인 절차를 SOP 에 명문화",
            created_by="최_파트",
            is_demo=True,
        )
        db.session.add(capa)
        db.session.commit()

    # ------------------------------------------------------------ 검토의견 문구 템플릿
    if not CommentTemplate.query.first():
        defaults = [
            ("qc_manager", "정상 · 기준충족", 1,
             "당월 정밀성(당월 CV·(Mean)%Diff·(CV)Diff) 및 L-J 관리 결과 모두 "
             "허용기준 이내로 정도관리 상태 양호함."),
            ("qc_manager", "경미 이탈 · 조치완료", 2,
             "일부 항목에서 관리한계 이탈이 확인되었으나 재검·재교정 후 회복을 "
             "확인하였으며, 관련 시정조치를 완료함."),
            ("qc_manager", "저농도 항목 참고", 3,
             "저농도 항목의 (Mean)%Diff 및 CV는 항목별 허용기준(≤10%)을 적용하여 "
             "판정하였으며 관리상 문제 없음."),
            ("qc_manager", "Lot 교체 반영", 4,
             "관리물질 Lot 교체에 따라 목표평균·SD를 재설정하였으며, 신규 Lot "
             "병행검사 결과 이상 없음."),
            ("pathologist", "검토 · 승인", 1,
             "상기 정도관리 결과 및 시정조치 내역을 검토함. 전반적 정도관리 "
             "상태 적합으로 판단하며 승인함."),
            ("pathologist", "조건부 승인 · 모니터링", 2,
             "검토 결과 적합하나 해당 항목에 대하여 익월 추세 모니터링을 "
             "권고함."),
            ("pathologist", "보완 후 재검토", 3,
             "일부 이탈 항목에 대한 원인분석·시정조치 근거가 미흡하여 보완 후 "
             "재검토를 요청함."),
        ]
        for role, title, order, body in defaults:
            db.session.add(CommentTemplate(role=role, title=title,
                           display_order=order, body=body, created_by="시스템"))
        db.session.commit()

    # ------------------------------------------------------------ 문서 메타 / 정도관리 물질
    if not DocumentMeta.query.get(1):
        analyte_text = (
            "LDH, Glu, BUN, Crea, T-P, Alb, T-Bil, D-Bil, AST, ALT, ALP, γ-GT, "
            "T-Cho, TG, HDL, LDL, UA, hs-CRP, Fe, UIBC, Ca, I.P, Amy, Lipa, CK, "
            "Mg, Na, K, Cl, T-CO2, RA, VDRL, TPLA")
        m = DocumentMeta(
            id=1, department="진단검사의학과", doc_number="LM-B-05",
            established_date="2005. 05. 01.", revised_date="2022. 01. 01.",
            revision_reason="문서번호 관리",
            doc_title="내부정도관리 종합검토 및 평가",
            eval_contents="정밀성 검증,L-J Chart",
            analyte_list=analyte_text)
        db.session.add(m)
        db.session.commit()

    if not QcMaterial.query.first():
        mats = [
            "InteliQ Assayed Multiqual Control 1, InteliQ Assayed Multiqual Control 3",
            "InteliQ Immunology Control 1, InteliQ Immunology Control 3",
            "InteliQ Urine Chemistry Control 1, InteliQ Urine Chemistry Control 2",
            "RPR Control (Neg.), RPR Control (Pos.)",
            "TPLA Control A, TPLA Control B",
            "SAA Control 1, SAA Control 2",
            "NGAL Control Low, NGAL Control High",
            "Ammonia Control Low, Ammonia Control High",
            "Ethanol Control 100, Ethanol Control 300",
            "Cystatin C Control Low, Cystatin C Control High",
            "PGⅠ,Ⅱ Control L, PGⅠ,Ⅱ Control H",
            "Trulab N, Trulab P - Lipase",
            "Multichem S plus (Assayed) 1, 2, 3 - TDM",
        ]
        # 데모: TDM(마지막) 은 미선택으로 두어 '선택 항목만 표기' 동작을 보여준다
        for i, label in enumerate(mats):
            db.session.add(QcMaterial(label=label, display_order=i + 1,
                           selected=(i < len(mats) - 1)))
        db.session.commit()

    # ------------------------------------------------------------ 평가장비 #2~#4 + 검사항목 배정
    for code, name in [("FX8-2", "TBA FX8 #2"), ("FX8-3", "TBA FX8 #3"),
                       ("FX8-4", "TBA FX8 #4")]:
        if not Instrument.query.filter_by(code=code).first():
            db.session.add(Instrument(code=code, name=name))
    db.session.commit()

    # FX8-1 장비별 담당자·전문의 지정 (데모: 최_파트=담당, 윤_전문=전문의)
    inst1 = Instrument.query.filter_by(code="FX8-1").first()
    if inst1 and inst1.manager_id is None:
        mgr = User.query.filter_by(username="qc").first()
        pat = User.query.filter_by(username="dr").first()
        inst1.manager_id = mgr.id if mgr else None
        inst1.pathologist_id = pat.id if pat else None
        db.session.commit()

    # FX8-1 검사항목 배정: 현재 import 된 검사항목(QcTarget) 전체를 활성 배정
    if inst1 and not InstrumentAnalyte.query.filter_by(instrument_id=inst1.id).first():
        aids = {t.analyte_id for t in
                QcTarget.query.filter_by(instrument_id=inst1.id).all()}
        for aid in aids:
            db.session.add(InstrumentAnalyte(instrument_id=inst1.id,
                           analyte_id=aid, active=True))
        db.session.commit()

    # ------------------------------------------------------------ 항목 특성별 평가기준 그룹
    if not CriteriaGroup.query.first():
        g_general = CriteriaGroup(name="일반 항목", cv_limit=5.0,
                                  mean_diff_limit=3.0, cv_diff_limit=3.0,
                                  display_order=1,
                                  description="일반 임상화학 정량 항목")
        g_low = CriteriaGroup(name="저농도 항목", cv_limit=10.0,
                              mean_diff_limit=5.0, cv_diff_limit=5.0,
                              display_order=2,
                              description="저농도 항목(담즙색소·CO₂·Mg 등) 완화 기준")
        g_qual = CriteriaGroup(name="면역·정성 항목", cv_limit=10.0,
                               mean_diff_limit=10.0, cv_diff_limit=10.0,
                               display_order=3,
                               description="RPR·TPLA 등 정성/반정량 항목")
        db.session.add_all([g_general, g_low, g_qual])
        db.session.commit()

        low_names = {"T.Bilirubin", "D.Bilirubin", "Total CO₂", "Total CO2",
                     "Mg", "MicroAlbumin(Quan)", "Lactic Acid(Lactate)"}
        qual_names = {"RPR 정밀(syphilis)", "TPLA(syphilis)", "RA (정량)",
                      "CRP (정량)"}
        for a in Analyte.query.all():
            if a.name in low_names:
                a.criteria_group_id = g_low.id
            elif a.name in qual_names:
                a.criteria_group_id = g_qual.id
            else:
                a.criteria_group_id = g_general.id
        db.session.commit()

    services.log_audit("SEED", detail="데모 시드 데이터 적재")
    return True
