"""내 계정 · 서명 이미지 관리 라우트."""
import base64
import io

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash)
from flask_login import login_required, current_user

from .. import db
from ..services import log_audit

bp = Blueprint("account", __name__, url_prefix="/account")

ALLOWED_MIME = {"image/png", "image/jpeg", "image/jpg", "image/gif",
                "image/webp", "image/bmp", "image/heic", "image/heif"}
MAX_UPLOAD_BYTES = 12_000_000   # 원본 허용 12MB (휴대폰 사진 대응)
MAX_WIDTH = 600                  # 저장 시 최대 폭(px)


def _process_signature(data, make_transparent=False):
    """업로드 이미지(휴대폰 사진 포함)를 서명용 PNG data URI 로 변환.

    - EXIF 회전 보정
    - 최대 폭 600px 로 축소
    - (선택) 흰 배경을 투명하게 처리
    반환: (data_uri, error_message)
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        # Pillow 미설치 시: 원본을 그대로 저장(형식 유지)
        if len(data) > 1_000_000:
            return None, "이미지 처리를 위해 Pillow 설치가 필요합니다(용량 초과)."
        return "data:image/png;base64," + base64.b64encode(data).decode(), None
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)            # 촬영 방향 보정
        im = im.convert("RGBA")
        if im.width > MAX_WIDTH:
            h = int(im.height * MAX_WIDTH / im.width)
            im = im.resize((MAX_WIDTH, h))
        if make_transparent:
            px = im.getdata()
            newpx = [(r, g, b, 0) if (r > 225 and g > 225 and b > 225)
                     else (r, g, b, a) for (r, g, b, a) in px]
            im.putdata(newpx)
        out = io.BytesIO()
        im.save(out, format="PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode(), None
    except Exception:
        return None, "이미지를 읽을 수 없습니다. PNG/JPG 등 일반 이미지 파일인지 확인하세요."


@bp.route("/")
@login_required
def index():
    return render_template("account.html")


@bp.route("/signature", methods=["POST"])
@login_required
def upload_signature():
    f = request.files.get("signature")
    if not f or not f.filename:
        flash("서명 이미지 파일을 선택하세요.", "warning")
        return redirect(url_for("account.index"))
    data = f.read()
    if len(data) > MAX_UPLOAD_BYTES:
        flash("이미지 원본 크기는 12MB 이하로 등록해 주세요.", "danger")
        return redirect(url_for("account.index"))
    make_transparent = request.form.get("transparent") == "on"
    uri, err = _process_signature(data, make_transparent=make_transparent)
    if err:
        flash(err, "danger")
        return redirect(url_for("account.index"))
    current_user.signature_image = uri
    db.session.commit()
    log_audit("SIGN_IMAGE_SET", entity="user", entity_id=current_user.id,
              detail=f"{current_user.name} 서명 이미지 등록"
                     + (" (배경 투명화)" if make_transparent else ""))
    flash("서명 이미지가 등록되었습니다. 전자서명 시 화면과 PDF에 표시됩니다.", "success")
    return redirect(url_for("account.index"))


@bp.route("/signature/clear", methods=["POST"])
@login_required
def clear_signature():
    current_user.signature_image = None
    db.session.commit()
    log_audit("SIGN_IMAGE_CLEAR", entity="user", entity_id=current_user.id,
              detail=f"{current_user.name} 서명 이미지 삭제")
    flash("서명 이미지가 삭제되었습니다.", "info")
    return redirect(url_for("account.index"))
