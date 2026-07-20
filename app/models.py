"""데이터 모델 (SQLAlchemy ORM).

우수검사실 인증 심사점검표의 내부정도관리 요구사항에 대응하는
엔티티를 정의한다.

  - Instrument / Analyte / ControlMaterial / Lot / QcTarget : 4.1 마스터
  - QcResult / MultiruleViolation                          : 4.2 QC입력·L-J·멀티룰
  - MonthlyReview / Signature / AuditLog                   : 4.3 검토·전자서명·감사추적
  - Capa                                                    : 4.4 시정조치
"""
from datetime import datetime, date
import hashlib
import json

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from . import db


# ---------------------------------------------------------------------------
# 사용자 / 권한
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(50), nullable=False)          # 성명 (서명 표기)
    title = db.Column(db.String(50))                          # 직함
    # role: qc_manager(정도관리담당) / pathologist(전문의) / admin
    role = db.Column(db.String(20), nullable=False, default="qc_manager")
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # 서명 이미지 (data URI, base64) — 전자서명 시 화면/PDF 에 표시
    signature_image = db.Column(db.Text)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def role_label(self):
        return {
            "qc_manager": "정도관리담당",
            "pathologist": "전문의",
            "admin": "관리자",
        }.get(self.role, self.role)


# ---------------------------------------------------------------------------
# 마스터 : 장비 / 검사항목 / 관리물질 / Lot / 목표값
# ---------------------------------------------------------------------------
class Instrument(db.Model):
    __tablename__ = "instrument"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)   # FX8-1
    name = db.Column(db.String(80), nullable=False)                # TBA FX8 #1
    department = db.Column(db.String(50), default="자동화학")
    # 평가장비별 지정 담당자(정도관리담당)·전문의 (변경 가능)
    manager_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    pathologist_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    manager = db.relationship("User", foreign_keys=[manager_id])
    pathologist = db.relationship("User", foreign_keys=[pathologist_id])


class CriteriaGroup(db.Model):
    """항목 특성별 정밀성 평가기준 그룹.

    검사항목의 특성(일반/저농도/면역·정성 등)에 따라 (Mean)%Diff·(CV)Diff·CV
    허용기준을 그룹 단위로 설정하고, 각 검사항목을 그룹에 배정한다.
    """
    __tablename__ = "criteria_group"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)     # 예: 일반 항목, 저농도 항목
    cv_limit = db.Column(db.Float, default=5.0)         # 당월 CV 허용기준 (%)
    mean_diff_limit = db.Column(db.Float, default=3.0)  # (Mean) %Diff 허용기준 (%)
    cv_diff_limit = db.Column(db.Float, default=3.0)    # (CV) Diff 허용기준 (%)
    display_order = db.Column(db.Integer, default=0)
    description = db.Column(db.String(200))


class Analyte(db.Model):
    __tablename__ = "analyte"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)   # Glucose
    short_name = db.Column(db.String(40))                          # Glu
    unit = db.Column(db.String(20))
    display_order = db.Column(db.Integer, default=0)
    # 저농도 물질 여부 (허용 CV ≤ 10% 적용 대상)
    low_concentration = db.Column(db.Boolean, default=False)
    # 항목 특성별 평가기준 그룹 (미지정 시 전역 기본값 사용)
    criteria_group_id = db.Column(db.Integer, db.ForeignKey("criteria_group.id"))
    criteria_group = db.relationship("CriteriaGroup", backref="analytes")


class InstrumentAnalyte(db.Model):
    """평가장비(기기번호)별 검사항목 배정.

    #번호 항목처럼 특정 장비에서만 시행하는 검사가 있으므로, 장비별로
    평가 대상 검사항목을 선택·관리한다. 분석 평가는 장비별로 배정된
    검사항목에 대해서만 진행된다.
    """
    __tablename__ = "instrument_analyte"
    id = db.Column(db.Integer, primary_key=True)
    instrument_id = db.Column(db.Integer, db.ForeignKey("instrument.id"), nullable=False)
    analyte_id = db.Column(db.Integer, db.ForeignKey("analyte.id"), nullable=False)
    active = db.Column(db.Boolean, default=True)
    analyte = db.relationship("Analyte")
    __table_args__ = (
        db.UniqueConstraint("instrument_id", "analyte_id", name="uq_inst_analyte"),
    )


class ControlMaterial(db.Model):
    __tablename__ = "control_material"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)   # InteliQ Assayed Multiqual Control 1
    manufacturer = db.Column(db.String(80))            # Bio-Rad
    lots = db.relationship("Lot", backref="material", lazy=True)


class Lot(db.Model):
    __tablename__ = "lot"
    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey("control_material.id"))
    lot_no = db.Column(db.String(40), nullable=False)      # 예: LOT-01
    level = db.Column(db.String(20), nullable=False)       # level1 / level3 / High / Low ...
    expiry_date = db.Column(db.Date)
    __table_args__ = (db.UniqueConstraint("lot_no", "level", name="uq_lot_level"),)


class QcTarget(db.Model):
    """검사항목 x Lot x level 별 목표 평균/SD (관리한계 산출 기준)."""
    __tablename__ = "qc_target"
    id = db.Column(db.Integer, primary_key=True)
    instrument_id = db.Column(db.Integer, db.ForeignKey("instrument.id"))
    analyte_id = db.Column(db.Integer, db.ForeignKey("analyte.id"))
    lot_id = db.Column(db.Integer, db.ForeignKey("lot.id"))
    level = db.Column(db.String(20), nullable=False)
    # 배정값(assigned/target) — %Diff 비교 기준
    target_mean = db.Column(db.Float, nullable=False)
    target_sd = db.Column(db.Float, nullable=False)
    # 운영/확립값(operating) — L-J 관리한계·Westgard 판정 중심선 (CLSI C24)
    oper_mean = db.Column(db.Float)
    oper_sd = db.Column(db.Float)
    unit = db.Column(db.String(20))
    effective_from = db.Column(db.Date, default=date.today)

    @property
    def center_mean(self):
        return self.oper_mean if self.oper_mean is not None else self.target_mean

    @property
    def center_sd(self):
        return self.oper_sd if self.oper_sd is not None else self.target_sd

    instrument = db.relationship("Instrument")
    analyte = db.relationship("Analyte")
    lot = db.relationship("Lot")

    @property
    def cv(self):
        if self.target_mean:
            return round(self.target_sd / self.target_mean * 100, 2)
        return None


class PrecisionSummary(db.Model):
    """월별 정밀성 통계 (LIS 정밀성검점 export 를 그대로 보존).

    LMB05 [표3] 평가기준(당월 CV, (Mean)%Diff, (CV)Diff)의 판정 근거가 되는
    LIS 계산값을 원본 그대로 저장하여, 일별 데이터 재계산과 무관하게
    실제 보고 수치를 재현한다.
    """
    __tablename__ = "precision_summary"
    id = db.Column(db.Integer, primary_key=True)
    instrument_id = db.Column(db.Integer, db.ForeignKey("instrument.id"))
    analyte_id = db.Column(db.Integer, db.ForeignKey("analyte.id"))
    lot_id = db.Column(db.Integer, db.ForeignKey("lot.id"))
    level = db.Column(db.String(20), nullable=False)
    year_month = db.Column(db.String(7), nullable=False)   # 2026-06
    target_mean = db.Column(db.Float)
    target_sd = db.Column(db.Float)
    prev_mean = db.Column(db.Float)
    cur_mean = db.Column(db.Float)
    cur_sd = db.Column(db.Float)
    prev_cv = db.Column(db.Float)
    cur_cv = db.Column(db.Float)
    mean_pct_diff = db.Column(db.Float)
    cv_diff = db.Column(db.Float)

    instrument = db.relationship("Instrument")
    analyte = db.relationship("Analyte")
    lot = db.relationship("Lot")

    __table_args__ = (
        db.UniqueConstraint("instrument_id", "analyte_id", "level",
                            "year_month", name="uq_precision_period"),
    )


# ---------------------------------------------------------------------------
# QC 결과 / 멀티룰 위반
# ---------------------------------------------------------------------------
class QcResult(db.Model):
    __tablename__ = "qc_result"
    id = db.Column(db.Integer, primary_key=True)
    target_id = db.Column(db.Integer, db.ForeignKey("qc_target.id"), nullable=False)
    result_date = db.Column(db.Date, nullable=False)
    run_seq = db.Column(db.Integer, default=1)        # 동일 일자 내 run 순번
    value = db.Column(db.Float, nullable=False)
    z_score = db.Column(db.Float)
    # 판정 결과 요약 (accept / warning / reject)
    status = db.Column(db.String(10), default="accept")
    rules = db.Column(db.String(120))                 # 위반 규칙 CSV (예: "1_3s,2_2s")
    action = db.Column(db.String(200))                # 조치사항

    target = db.relationship("QcTarget", backref="results")


# ---------------------------------------------------------------------------
# 월별 검토 / 전자서명 / 감사추적
# ---------------------------------------------------------------------------
class MonthlyReview(db.Model):
    """월 단위 내부정도관리 종합검토 (LMB05) 레코드."""
    __tablename__ = "monthly_review"
    id = db.Column(db.Integer, primary_key=True)
    instrument_id = db.Column(db.Integer, db.ForeignKey("instrument.id"))
    year_month = db.Column(db.String(7), nullable=False)   # 2026-06
    # 상태: draft → manager_signed → completed
    status = db.Column(db.String(20), default="draft")
    manager_comment = db.Column(db.Text)                   # 정도관리담당 검토의견
    pathologist_comment = db.Column(db.Text)               # 전문의 검토의견
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    instrument = db.relationship("Instrument")
    signatures = db.relationship("Signature", backref="review", lazy=True)
    capas = db.relationship("Capa", backref="review", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("instrument_id", "year_month", name="uq_review_period"),
    )

    def content_hash(self):
        """검토 대상 데이터의 무결성 해시(SHA-256).

        전자서명 시점의 정밀성 요약·위반내역·검토의견을 직렬화하여 해시한다.
        서명 이후 데이터가 변경되면 해시가 달라져 무결성 훼손을 탐지할 수 있다.
        """
        from .services import build_review_payload  # 지연 import (순환 방지)
        payload = build_review_payload(self)
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def status_label(self):
        return {
            "draft": "작성중",
            "manager_signed": "담당 서명완료",
            "completed": "검토완료",
        }.get(self.status, self.status)


class Signature(db.Model):
    """전자서명 기록 (비밀번호 재인증 기반)."""
    __tablename__ = "signature"
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("monthly_review.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    role = db.Column(db.String(20), nullable=False)     # qc_manager / pathologist
    signer_name = db.Column(db.String(50))
    signed_at = db.Column(db.DateTime, default=datetime.utcnow)
    content_hash = db.Column(db.String(64))             # 서명 시점 무결성 해시
    meaning = db.Column(db.String(100))                 # 서명 의미(승인/검토)
    signature_image = db.Column(db.Text)                # 서명 시점 서명이미지 스냅샷

    user = db.relationship("User")


class AuditLog(db.Model):
    """감사추적 로그 — 누가, 언제, 무엇을 처리했는지."""
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    user_name = db.Column(db.String(50))
    action = db.Column(db.String(40), nullable=False)   # LOGIN / IMPORT / SIGN / CAPA_CREATE ...
    entity = db.Column(db.String(40))
    entity_id = db.Column(db.Integer)
    detail = db.Column(db.Text)
    ip = db.Column(db.String(45))

    user = db.relationship("User")


# ---------------------------------------------------------------------------
# 시정조치 (CAPA)
# ---------------------------------------------------------------------------
class DocumentMeta(db.Model):
    """문서 머리글 메타데이터 (문서번호·제정/개정일시·개정사유) 및 보고서 현황 설정.

    단일 레코드(id=1)로 운영한다.
    """
    __tablename__ = "document_meta"
    id = db.Column(db.Integer, primary_key=True)
    institution = db.Column(db.String(120), default="")          # 기관명(선택)
    department = db.Column(db.String(80), default="진단검사의학과")
    doc_number = db.Column(db.String(40), default="LM-B-05")
    established_date = db.Column(db.String(40), default="2005. 05. 01.")
    revised_date = db.Column(db.String(40), default="2022. 01. 01.")
    revision_reason = db.Column(db.String(120), default="문서번호 관리")
    doc_title = db.Column(db.String(80), default="내부정도관리 종합검토 및 평가")
    # 평가내용 체크 항목 (콤마 구분) — 보고서에는 체크된 것만 표기
    eval_contents = db.Column(db.Text, default="정밀성 검증,L-J Chart")
    # 평가항목(analyte) 본문 텍스트
    analyte_list = db.Column(db.Text, default="")

    @property
    def eval_content_list(self):
        return [x.strip() for x in (self.eval_contents or "").split(",") if x.strip()]

    @staticmethod
    def get():
        m = DocumentMeta.query.get(1)
        if not m:
            m = DocumentMeta(id=1)
            db.session.add(m)
            db.session.commit()
        return m


class QcMaterial(db.Model):
    """정도관리 물질 목록 — 보고서 '2. 정도관리 물질'에 선택된 항목만 표기."""
    __tablename__ = "qc_material_item"
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(200), nullable=False)   # 물질명(들)
    selected = db.Column(db.Boolean, default=True)      # 보고서 표기 여부
    display_order = db.Column(db.Integer, default=0)


class CommentTemplate(db.Model):
    """검토의견 문구 템플릿 — 담당/전문의별로 등록해 두고 선택·삽입·편집하여 사용."""
    __tablename__ = "comment_template"
    id = db.Column(db.Integer, primary_key=True)
    # 대상 역할: qc_manager(정도관리담당) / pathologist(전문의)
    role = db.Column(db.String(20), nullable=False, default="qc_manager")
    title = db.Column(db.String(80), nullable=False)   # 목록에 표시할 짧은 제목
    body = db.Column(db.Text, nullable=False)          # 실제 삽입될 문구
    display_order = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def role_label(self):
        return {"qc_manager": "정도관리담당", "pathologist": "전문의"}.get(
            self.role, self.role)


class Capa(db.Model):
    __tablename__ = "capa"
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey("monthly_review.id"))
    qc_result_id = db.Column(db.Integer, db.ForeignKey("qc_result.id"))
    analyte_name = db.Column(db.String(80))
    event_summary = db.Column(db.String(200))     # 이상 내역 (예: Glucose L3 1_3s 위반)
    cause = db.Column(db.Text)                     # 원인 분석
    action = db.Column(db.Text)                    # 조치 내용
    prevention = db.Column(db.Text)                # 재발 방지 대책
    created_by = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved = db.Column(db.Boolean, default=False)
    # 시연용 데모 데이터 여부 (실측 QC 데이터와 구분 표시)
    is_demo = db.Column(db.Boolean, default=False)
