"""LIS export 파일 파서 / import 로직.

검사정보시스템(LIS)에서 내려받는 3종 파일 형식을 지원한다.

  (A) 정밀성검점  export : LOTNO, 검사항목, 레벨, Target Mean/SD, 전월/당월 Mean,
                          당월 SD, 전월/당월 CV, %Diff(Mean), Diff(CV)
  (B) L-J 일별   export : LOT NO, 장비명, 검사항목명, 레벨, Mean, SD, ...,
                          20260601_1, 20260601_2 ... 일자별 측정값
  (C) 물질별 일일결과 export : 검사항목명, 결과, N, 상태, WG, 룰, 조치사항

CSV(UTF-8-SIG) 또는 .xls 를 입력으로 받는다.
"""
import csv
import io
import re
from datetime import date, datetime

from . import db
from .models import (
    Instrument, Analyte, ControlMaterial, Lot, QcTarget, QcResult,
    PrecisionSummary,
)

# 저농도 물질(허용 CV ≤ 10%) 지정 — LMB05 [표4] 취지 반영(대표 항목)
LOW_CONC_ANALYTES = {
    "T.Bilirubin", "D.Bilirubin", "Total CO₂", "Total CO2",
    "Mg", "MicroAlbumin(Quan)", "Lactic Acid(Lactate)",
}

DISPLAY_ORDER = [
    "LDH", "Glucose", "BUN(Blood Urea Nitrogen)", "Creatinine", "T.Protein",
    "Albumin", "T.Cholesterol", "T.Bilirubin", "D.Bilirubin",
    "Alkaline phosphatase(ALP)", "AST (GOT)", "ALT (GPT)", "γ-GT", "Uric acid",
    "Triglyceride", "HDL-Cholesterol", "LDL-Cholesterol", "Fe", "UIBC", "Ca",
    "I.Phos", "Amylase", "CK", "Mg", "Na", "K", "Cl", "Total CO₂",
]


def _read_rows(path_or_bytes, filename=""):
    """CSV 또는 xls 파일에서 행 리스트(list[list[str]])를 얻는다."""
    if filename.lower().endswith((".xls", ".xlsx")):
        import xlrd
        wb = (xlrd.open_workbook(file_contents=path_or_bytes)
              if isinstance(path_or_bytes, (bytes, bytearray))
              else xlrd.open_workbook(path_or_bytes))
        sh = wb.sheet_by_index(0)
        return [[str(sh.cell_value(r, c)) for c in range(sh.ncols)]
                for r in range(sh.nrows)]
    # CSV
    if isinstance(path_or_bytes, (bytes, bytearray)):
        text = path_or_bytes.decode("utf-8-sig", errors="replace")
    else:
        with open(path_or_bytes, encoding="utf-8-sig") as f:
            text = f.read()
    return list(csv.reader(io.StringIO(text)))


def _f(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def get_or_create_instrument(code, name=None):
    inst = Instrument.query.filter_by(code=code).first()
    if not inst:
        inst = Instrument(code=code, name=name or code)
        db.session.add(inst)
        db.session.flush()
    return inst


def get_or_create_analyte(name):
    a = Analyte.query.filter_by(name=name).first()
    if not a:
        order = DISPLAY_ORDER.index(name) if name in DISPLAY_ORDER else 999
        a = Analyte(name=name, display_order=order,
                    low_concentration=(name in LOW_CONC_ANALYTES))
        db.session.add(a)
        db.session.flush()
    return a


def get_or_create_lot(lot_no, level, material_name="InteliQ Multiqual (InteliQ)"):
    lot = Lot.query.filter_by(lot_no=lot_no, level=level).first()
    if not lot:
        mat = ControlMaterial.query.filter_by(name=material_name).first()
        if not mat:
            mat = ControlMaterial(name=material_name, manufacturer="Bio-Rad")
            db.session.add(mat)
            db.session.flush()
        lot = Lot(material_id=mat.id, lot_no=lot_no, level=level)
        db.session.add(lot)
        db.session.flush()
    return lot


def get_or_create_target(instrument, analyte, lot, level, tmean, tsd):
    t = QcTarget.query.filter_by(
        instrument_id=instrument.id, analyte_id=analyte.id, lot_id=lot.id,
        level=level).first()
    if not t:
        t = QcTarget(instrument_id=instrument.id, analyte_id=analyte.id,
                     lot_id=lot.id, level=level,
                     target_mean=tmean, target_sd=tsd)
        db.session.add(t)
        db.session.flush()
    else:
        t.target_mean, t.target_sd = tmean, tsd
    return t


# ---------------------------------------------------------------------------
# (A) 정밀성 export
# ---------------------------------------------------------------------------
def import_precision(path_or_bytes, filename="", instrument_code="FX8-1",
                     instrument_name="TBA FX8 #1", year_month="2026-06"):
    """정밀성 export → 마스터(항목/Lot/목표값) + 월별 정밀성요약 등록.

    LIS 가 계산한 당월 Mean/SD/CV, %Diff(Mean), Diff(CV) 를 PrecisionSummary 에
    원본 그대로 보존한다(LMB05 [표3] 판정 근거).
    """
    rows = _read_rows(path_or_bytes, filename)
    inst = get_or_create_instrument(instrument_code, instrument_name)
    created = 0
    for row in rows[1:]:
        if len(row) < 5 or not row[1].strip():
            continue
        lot_no, analyte_name, level = row[0].strip(), row[1].strip(), row[2].strip()
        tmean, tsd = _f(row[3]), _f(row[4])
        if tmean is None or tsd is None:
            continue
        analyte = get_or_create_analyte(analyte_name)
        lot = get_or_create_lot(lot_no, level)
        get_or_create_target(inst, analyte, lot, level, tmean, tsd)

        # 정밀성 요약(원본 LIS 계산값) 보존
        prev_mean, cur_mean, cur_sd = _f(row[5]), _f(row[6]), _f(row[7])
        prev_cv, cur_cv = _f(row[8]), _f(row[9])
        mean_pct_diff = _f(row[10]) if len(row) > 10 else None
        cv_diff = _f(row[11]) if len(row) > 11 else None
        ps = PrecisionSummary.query.filter_by(
            instrument_id=inst.id, analyte_id=analyte.id, level=level,
            year_month=year_month).first()
        if not ps:
            ps = PrecisionSummary(instrument_id=inst.id, analyte_id=analyte.id,
                                  lot_id=lot.id, level=level,
                                  year_month=year_month)
            db.session.add(ps)
        ps.lot_id = lot.id
        ps.target_mean, ps.target_sd = tmean, tsd
        ps.prev_mean, ps.cur_mean, ps.cur_sd = prev_mean, cur_mean, cur_sd
        ps.prev_cv, ps.cur_cv = prev_cv, cur_cv
        ps.mean_pct_diff, ps.cv_diff = mean_pct_diff, cv_diff
        created += 1
    db.session.commit()
    return {"instrument": inst.code, "targets": created}


# ---------------------------------------------------------------------------
# (B) L-J 일별 export
# ---------------------------------------------------------------------------
def import_lj_daily(path_or_bytes, filename="", instrument_code="FX8-1"):
    """L-J 일별 측정값 export → QcResult 일별 데이터 적재."""
    rows = _read_rows(path_or_bytes, filename)
    header = rows[0]
    inst = get_or_create_instrument(instrument_code)

    # 날짜 컬럼 인덱스 파악 (헤더가 20260601_1 형태)
    date_cols = []
    for idx, h in enumerate(header):
        m = re.match(r"(\d{8})", str(h).strip())
        if m:
            date_cols.append((idx, m.group(1)))

    # 컬럼 위치 (LOT NO/검사항목명/레벨/Mean/SD)
    def col(name):
        for i, h in enumerate(header):
            if str(h).strip() == name:
                return i
        return None

    ci_lot, ci_an, ci_lv = col("LOT NO"), col("검사항목명"), col("레벨")
    ci_mean, ci_sd = col("Mean"), col("SD")

    inserted = 0
    for row in rows[1:]:
        if not row or len(row) <= max(ci_lot or 0, ci_an or 0):
            continue
        lot_no = row[ci_lot].strip()
        analyte_name = row[ci_an].strip()
        level = row[ci_lv].strip()
        tmean, tsd = _f(row[ci_mean]), _f(row[ci_sd])
        if not analyte_name:
            continue
        analyte = get_or_create_analyte(analyte_name)
        lot = get_or_create_lot(lot_no, level)
        target = get_or_create_target(inst, analyte, lot, level, tmean, tsd)

        # 일자별 값 적재
        seq_by_date = {}
        for idx, dstr in date_cols:
            if idx >= len(row):
                continue
            v = _f(row[idx])
            if v is None:
                continue
            d = datetime.strptime(dstr, "%Y%m%d").date()
            seq_by_date[d] = seq_by_date.get(d, 0) + 1
            exists = QcResult.query.filter_by(
                target_id=target.id, result_date=d,
                run_seq=seq_by_date[d]).first()
            if exists:
                exists.value = v
            else:
                db.session.add(QcResult(target_id=target.id, result_date=d,
                                        run_seq=seq_by_date[d], value=v))
                inserted += 1
    db.session.commit()
    return {"results": inserted}


# ---------------------------------------------------------------------------
# (C) 물질별 일일결과 export
# ---------------------------------------------------------------------------
def import_daily_results(path_or_bytes, filename="", instrument_code="FX8-1",
                         result_date=None, level="level1", lot_no="10341T-5"):
    """물질별 일일결과 export → 지정 일자 단일 run 결과 적재."""
    rows = _read_rows(path_or_bytes, filename)
    inst = get_or_create_instrument(instrument_code)
    rdate = result_date or date.today()

    def find(colname, header):
        for i, h in enumerate(header):
            if colname in str(h):
                return i
        return None

    header = rows[0]
    ci_an = find("검사항목", header)
    ci_val = find("결과", header)
    inserted = 0
    for row in rows[1:]:
        if ci_an is None or len(row) <= ci_an:
            continue
        analyte_name = row[ci_an].strip()
        val = _f(row[ci_val]) if ci_val is not None else None
        if not analyte_name or val is None:
            continue
        analyte = Analyte.query.filter_by(name=analyte_name).first()
        if not analyte:
            continue
        target = QcTarget.query.filter_by(
            instrument_id=inst.id, analyte_id=analyte.id, level=level).first()
        if not target:
            continue
        seq = (QcResult.query.filter_by(target_id=target.id, result_date=rdate)
               .count()) + 1
        db.session.add(QcResult(target_id=target.id, result_date=rdate,
                                run_seq=seq, value=val))
        inserted += 1
    db.session.commit()
    return {"results": inserted}
