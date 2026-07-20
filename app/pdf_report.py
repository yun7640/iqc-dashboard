"""월간 QC 리포트(PDF) 자동 생성 — LMB05 '내부정도관리 종합검토 및 평가' 재현.

ReportLab 내장 한글 CID 폰트(HYSMyeongJo-Medium)를 사용하므로 외부 폰트
파일 없이 한글 출력이 가능하다.
"""
import os
import base64
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                Spacer, HRFlowable, Image, PageBreak)


def _sig_image(data_uri, max_w=38 * mm, max_h=16 * mm):
    """서명 이미지(data URI)를 ReportLab Image 플로우어블로 변환(비율 유지)."""
    if not data_uri or not str(data_uri).startswith("data:"):
        return None
    try:
        b64 = data_uri.split(",", 1)[1]
        raw = base64.b64decode(b64)
        bio = BytesIO(raw)
        iw, ih = ImageReader(bio).getSize()
        if not iw or not ih:
            return None
        ratio = min(max_w / iw, max_h / ih)
        bio.seek(0)
        return Image(bio, width=iw * ratio, height=ih * ratio)
    except Exception:
        return None

# 한글 폰트: 번들된 NanumGothic(OFL) TTF 를 PDF 에 임베드하여 어느 환경에서도
# 한글이 표시되도록 한다. 폰트 파일이 없으면 내장 CID 폰트로 대체한다.
_FONT_DIR = os.path.join(os.path.dirname(__file__), "static", "fonts")
FONT = "NanumGothic"
FONT_BOLD = "NanumGothic-Bold"
try:
    pdfmetrics.registerFont(TTFont(FONT, os.path.join(_FONT_DIR, "NanumGothic.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, os.path.join(_FONT_DIR, "NanumGothicBold.ttf")))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD)
except Exception:  # pragma: no cover
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    FONT = FONT_BOLD = "HYSMyeongJo-Medium"


def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("kr", parent=ss["Normal"], fontName=FONT,
                          fontSize=8.5, leading=12)
    title = ParagraphStyle("krT", parent=base, fontSize=15, leading=19,
                           alignment=1, spaceAfter=2)
    h = ParagraphStyle("krH", parent=base, fontSize=10.5, leading=14,
                       spaceBefore=8, spaceAfter=3, textColor=colors.HexColor("#1c3d5a"))
    small = ParagraphStyle("krS", parent=base, fontSize=7.5, leading=10)
    return base, title, h, small


def build_pdf(buf, inst, review, rows, capas, signatures, integrity_ok,
              meta=None, materials=None, assigned_names=None, match=None,
              crit_groups=None):
    base, title, h, small = _styles()

    # 문서 메타 기본값
    dept = getattr(meta, "department", None) or "진단검사의학과"
    doc_no = getattr(meta, "doc_number", None) or "LM-B-05"
    est = getattr(meta, "established_date", None) or "2005. 05. 01."
    rev = getattr(meta, "revised_date", None) or "2022. 01. 01."
    reason = getattr(meta, "revision_reason", None) or "문서번호 관리"
    doc_title = getattr(meta, "doc_title", None) or "내부정도관리 종합검토 및 평가"
    eval_contents = (meta.eval_content_list if meta and meta.eval_content_list
                     else ["정밀성 검증", "L-J Chart"])
    analyte_text = getattr(meta, "analyte_list", None) or ""

    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            title=f"IQC {inst.code} {review.year_month}")
    E = []

    # ---- 문서 머리글 (문서번호 등)
    head = Table([
        [dept, "문서번호", doc_no],
        ["", "제정일시", est],
        [doc_title, "개정일시", rev],
        ["", "개정사유", reason],
    ], colWidths=[95 * mm, 30 * mm, 55 * mm])
    head.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("SPAN", (0, 0), (0, 1)), ("SPAN", (0, 2), (0, 3)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("FONTSIZE", (0, 2), (0, 2), 11),
        ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#eef3f8")),
    ]))
    E.append(head)
    E.append(Spacer(1, 6))

    ym = review.year_month
    y, m = ym.split("-")

    # ---- 1. 정도관리 현황
    E.append(Paragraph("1. 정도관리 현황", h))
    # 평가장비: #1~#4 체크 표기
    inst_line = "   ".join(
        f"{'☑' if inst.code == 'FX8-'+str(n) else '☐'} TBA FX8 #{n}"
        for n in range(1, 5))
    content_line = "   ".join(f"☑ {c}" for c in eval_contents) + \
        f"    (평가 {len(rows)} 항목·레벨)"
    status_rows = [
        ["평가기간", Paragraph(f"{y} 년  {int(m)} 월", small)],
        ["평가장비", Paragraph(inst_line, small)],
        ["평가내용", Paragraph(content_line, small)],
    ]
    # 평가항목: 장비별 배정 검사항목 연동 (없으면 메타 본문)
    item_text = ", ".join(assigned_names) if assigned_names else analyte_text
    if item_text:
        status_rows.append(["평가항목", Paragraph(item_text, small)])
    status1 = Table(status_rows, colWidths=[26 * mm, 154 * mm])
    status1.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    E.append(status1)

    # ---- 2. 정도관리 물질 (선택된 물질만)
    if materials:
        E.append(Paragraph("2. 정도관리 물질", h))
        cells = [Paragraph("☑ " + m.label, small) for m in materials]
        # 2열 배치
        mat_rows = []
        for i in range(0, len(cells), 2):
            left = cells[i]
            right = cells[i + 1] if i + 1 < len(cells) else ""
            mat_rows.append([left, right])
        mtbl = Table(mat_rows, colWidths=[90 * mm, 90 * mm])
        mtbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        E.append(mtbl)

    # ---- 검사항목 매칭 알림
    if match and match.get("configured") and not match.get("ok"):
        parts = ["⚠ 검사항목 매칭 불일치 — LIS 결과와 장비 배정 검사항목이 일치하지 않습니다."]
        if match.get("missing"):
            parts.append("결과 누락: " + ", ".join(match["missing"]))
        if match.get("unexpected"):
            parts.append("미설정 항목: " + ", ".join(match["unexpected"]))
        E.append(Paragraph(" / ".join(parts), ParagraphStyle(
            "mm", parent=small, textColor=colors.HexColor("#c0392b"))))

    # ---- 3. 분석 평가기준 (항목 특성별 그룹)
    E.append(Paragraph("3. 분석 평가기준 (항목 특성별)", h))
    if crit_groups:
        cdata = [["항목 특성 그룹", "당월 CV", "(Mean)%Diff", "(CV)Diff", "해당 검사항목"]]
        for g in crit_groups:
            cdata.append([
                Paragraph(g["name"], small),
                f"≤ {g['cv_limit']}%", f"≤ {g['mean_diff_limit']}%",
                f"≤ {g['cv_diff_limit']}",
                Paragraph(", ".join(g["analytes"]), small),
            ])
        ct = Table(cdata, colWidths=[26 * mm, 16 * mm, 22 * mm, 16 * mm, 100 * mm],
                   repeatRows=1)
        ct.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1c3d5a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        E.append(ct)
    E.append(Paragraph(
        "L-J Chart — Westgard 멀티룰(1₂ₛ·1₃ₛ·2₂ₛ·R₄ₛ·4₁ₛ) 자동판정 (10ₓ 미적용). "
        "판정: 위 기준 및 일별 멀티룰 거부 0건을 모두 충족하면 적합, 아니면 확인.", small))

    # ---- 정밀성 종합검토 표 (전월↔당월 비교)
    # 정밀성 종합검토 표는 〔별첨〕 으로 문서 말미(전자서명 뒤)에 배치한다.
    E.append(Paragraph(
        f"■ 정밀성 종합검토 결과 — 상세 표는 문서 말미 〔별첨〕 참조 "
        f"(전월 → 당월, 총 {len(rows)} 항목·레벨).", small))
    appendix_elems = [Paragraph("〔별첨〕 정밀성 종합검토 결과 (전월 → 당월)", h)]
    header = ["검사항목", "Lv", "Target\nMean", "Target\nSD", "전월\nMean",
              "당월\nMean", "당월\nSD", "전월\nCV", "당월\nCV",
              "(Mean)\n%Diff", "(CV)\nDiff", "위반", "판정"]
    data = [header]

    def fnum(v, pct=False):
        if v is None:
            return "-"
        return f"{v:.2f}{'%' if pct else ''}"

    for r in rows:
        data.append([
            r["analyte"], r["level"].replace("level", "L"),
            f'{r["target_mean"]:.2f}', f'{r["target_sd"]:.2f}',
            fnum(r["prev_mean"]), f'{r["cur_mean"]:.2f}', f'{r["cur_sd"]:.2f}',
            fnum(r["prev_cv"], True), f'{r["cur_cv"]:.2f}%',
            fnum(r["mean_pct_diff"]), fnum(r["cv_diff"]),
            str(r["n_reject"]) if r["n_reject"] else "-",
            "적합" if r["pass"] else "확인",
        ])
    tbl = Table(data, colWidths=[30*mm, 7*mm, 15*mm, 13*mm, 15*mm, 15*mm,
                                 13*mm, 13*mm, 13*mm, 15*mm, 13*mm, 8*mm, 11*mm],
                repeatRows=1)
    tstyle = [
        ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 6),
        ("FONTSIZE", (0, 0), (-1, 0), 5.6),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1c3d5a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        # 전월 컬럼(Target SD 다음의 전월 Mean=4, 전월 CV=7) 음영
        ("BACKGROUND", (4, 1), (4, -1), colors.HexColor("#eef3f8")),
        ("BACKGROUND", (7, 1), (7, -1), colors.HexColor("#eef3f8")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i, r in enumerate(rows, start=1):
        if not r["pass"]:
            tstyle.append(("BACKGROUND", (0, i), (3, i),
                           colors.HexColor("#fdecea")))
            tstyle.append(("BACKGROUND", (5, i), (-1, i),
                           colors.HexColor("#fdecea")))
            tstyle.append(("TEXTCOLOR", (12, i), (12, i), colors.HexColor("#c0392b")))
    tbl.setStyle(TableStyle(tstyle))
    appendix_elems.append(tbl)

    # ---- 4. 시정조치
    if capas:
        E.append(Paragraph("■ 시정조치(CAPA) 기록", h))
        if any(getattr(c, "is_demo", False) for c in capas):
            E.append(Paragraph(
                "※ '데모' 표시 항목은 실제 LIS 데이터가 아니라 워크플로 시연용 "
                "가상 이벤트입니다.", ParagraphStyle(
                    "demo", parent=small, textColor=colors.HexColor("#b8860b"))))
        cdata = [["검사항목", "이상 내역", "원인/조치/재발방지", "상태"]]
        for c in capas:
            demo_tag = " [데모]" if getattr(c, "is_demo", False) else ""
            cdata.append([
                Paragraph((c.analyte_name or "") + demo_tag, small),
                Paragraph(c.event_summary or "", small),
                Paragraph(f"원인: {c.cause or '-'}<br/>조치: {c.action or '-'}"
                          f"<br/>재발방지: {c.prevention or '-'}", small),
                "완료" if c.resolved else "진행",
            ])
        ct = Table(cdata, colWidths=[24*mm, 45*mm, 96*mm, 15*mm], repeatRows=1)
        ct.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1c3d5a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        E.append(ct)

    # ---- 검토의견
    E.append(Paragraph("■ 검토의견", h))
    op = Table([
        ["정도관리담당 의견", Paragraph(review.manager_comment or "-", small)],
        ["전문의 검토의견", Paragraph(review.pathologist_comment or "-", small)],
    ], colWidths=[35 * mm, 145 * mm])
    op.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    E.append(op)

    # ---- 4. 전문의 검토 및 평가 (전자서명란)
    E.append(Paragraph("4. 전문의 검토 및 평가 (전자서명)", h))

    def sig_cell(role):
        s = signatures.get(role)
        if not s:
            return Paragraph("(미서명)", small)
        txt = Paragraph(
            f"{s.signer_name}  [전자서명]<br/>"
            f"{s.signed_at.strftime('%Y-%m-%d %H:%M')}<br/>"
            f"의미: {s.meaning}<br/>"
            f"무결성: {(s.content_hash or '')[:16]}…", small)
        img = _sig_image(getattr(s, "signature_image", None))
        return [img, txt] if img else [txt]

    sig = Table([
        ["정도관리담당 / 확인일시", sig_cell("qc_manager")],
        ["전 문 의 / 검토일시", sig_cell("pathologist")],
    ], colWidths=[45 * mm, 135 * mm])
    sig.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    E.append(sig)

    # ---- 무결성 / 감사추적 안내
    E.append(Spacer(1, 4))
    if integrity_ok is True:
        note = ("✔ 전자서명 시점의 검토대상 데이터 무결성 해시가 현재 데이터와 "
                "일치합니다 (변조 없음).")
        col = colors.HexColor("#1e7e34")
    elif integrity_ok is False:
        note = ("⚠ 서명 이후 검토대상 데이터가 변경되었습니다. 무결성 해시 불일치 — "
                "재검토·재서명이 필요합니다.")
        col = colors.HexColor("#c0392b")
    else:
        note = "본 리포트는 아직 전자서명이 완료되지 않은 상태입니다."
        col = colors.grey
    E.append(Paragraph(note, ParagraphStyle("nt", parent=small, textColor=col)))
    E.append(HRFlowable(width="100%", thickness=0.4, color=colors.grey,
                        spaceBefore=4, spaceAfter=2))
    E.append(Paragraph(
        f"문서번호 LM-B-05 · 장비 {inst.code} · 평가기간 {ym} · "
        f"생성일시 자동 · 본 문서는 웹 대시보드에서 전자적으로 검토·서명되었으며 "
        f"모든 생성·수정·서명 행위는 감사추적 로그로 관리됩니다.", small))

    # ---- 〔별첨〕 정밀성 종합검토 결과 (전자서명 다음 페이지)
    E.append(PageBreak())
    E.extend(appendix_elems)

    doc.build(E)
    return buf
