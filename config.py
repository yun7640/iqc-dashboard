"""애플리케이션 설정.

로컬 실행형 오픈소스 배포를 전제로, 별도 서버·DB 설치 없이
단일 SQLite 파일로 동작하도록 구성한다.
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)


def _load_secret_key():
    """세션 서명용 비밀키.

    환경변수 IQC_SECRET_KEY 가 있으면 사용하고, 없으면 instance/secret_key.txt
    에 무작위 키를 1회 생성·보관하여 서버 재시작·다중 사용자 환경에서도 세션이
    안정적으로 유지되도록 한다(개발용 고정키를 그대로 쓰지 않음).
    """
    env = os.environ.get("IQC_SECRET_KEY")
    if env:
        return env
    path = os.path.join(INSTANCE_DIR, "secret_key.txt")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    import secrets
    key = secrets.token_hex(32)
    with open(path, "w") as f:
        f.write(key)
    return key


class Config:
    SECRET_KEY = _load_secret_key()
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "IQC_DATABASE_URI", "sqlite:///" + os.path.join(INSTANCE_DIR, "iqc.sqlite3")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 업로드 요청 최대 크기 (서명 이미지 등) — 4MB
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024
    # 저장소 정책값 (심사 평가기준)
    CV_LIMIT = 5.0          # 당월 CV 허용기준 (%)
    CV_LIMIT_LOW = 10.0     # 저농도 물질 CV 허용기준 (%)
    MEAN_DIFF_LIMIT = 3.0   # (Mean) % Diff 허용기준 (%)
    CV_DIFF_LIMIT = 3.0     # (CV) Diff 허용기준 (%)
