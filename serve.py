"""검사실 인트라넷 공유 / 클라우드(Railway) 배포용 실행 스크립트.

로컬(인트라넷) 운영:
    python serve.py
    - 같은 네트워크의 다른 PC/휴대폰이 브라우저로 접속.

클라우드(Railway 등) 배포:
    - 플랫폼이 주입하는 PORT 환경변수를 자동 사용(0.0.0.0 바인딩).
    - DB가 비어 있으면(최초 배포) 데모 시드를 자동 적재 → 심사위원이 바로 로그인 체험.

환경변수(선택):
    PORT            : 클라우드 플랫폼이 주입(우선). 없으면 IQC_PORT(기본 5000).
    IQC_HOST        : 바인딩 주소(기본 0.0.0.0).
    IQC_SECRET_KEY  : 세션 서명키. 배포 환경에서는 값을 지정해 두면 재배포에도 세션 유지.
    IQC_DATABASE_URI: DB 접속 URI(기본 instance/iqc.sqlite3).
"""
import os
import socket

from app import create_app

app = create_app()


def _ensure_seeded():
    """DB 스키마 생성 + (비어 있으면) 데모 시드 자동 적재.

    클라우드 최초 배포 시 데이터가 없으면 데모 계정·QC 데이터를 자동으로 넣어,
    별도 CLI 실행 없이 온라인에서 곧바로 로그인·체험이 가능하도록 한다.
    """
    from app import db
    from app.models import User, Analyte
    with app.app_context():
        db.create_all()
        try:
            # 계정이 없거나(최초) 데이터가 비어 있으면(부분 시드/파일누락) 시드 실행
            need = User.query.count() == 0 or Analyte.query.count() == 0
        except Exception:
            need = True
        if need:
            from app.seed import run_seed
            run_seed()
            print("[init] 데모 시드 자동 적재 완료.")
        else:
            print("[init] 기존 데이터 유지(시드 생략).")


def _all_lan_ips():
    """이 PC의 모든 IPv4 주소(랜카드별)를 반환. 유선/무선이 다르면 모두 표시."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       family=socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    ips.sort(key=lambda x: x.startswith("100."))
    return ips or ["127.0.0.1"]


if __name__ == "__main__":
    # 클라우드 플랫폼(Railway 등)은 PORT 를 주입한다. 없으면 IQC_PORT(기본 5000).
    port = int(os.environ.get("PORT") or os.environ.get("IQC_PORT", "5000"))
    host = os.environ.get("IQC_HOST", "0.0.0.0")
    is_cloud = bool(os.environ.get("PORT"))

    # 최초 실행 시 데모 시드 자동 적재
    _ensure_seeded()

    if is_cloud:
        print("=" * 60)
        print(" 내부정도관리(IQC) 웹 대시보드 — 클라우드 배포 실행")
        print(f"   0.0.0.0:{port} 에서 서비스 (플랫폼 도메인으로 접속)")
        print("=" * 60)
    else:
        ips = _all_lan_ips()
        print("=" * 60)
        print(" 내부정도관리(IQC) 웹 대시보드 — 인트라넷 공유 실행")
        print(f"   이 PC(서버)에서   : http://127.0.0.1:{port}")
        print("   다른 PC/휴대폰에서 아래 주소 중 '접속 기기와 같은 대역'을 사용:")
        for ip in ips:
            print(f"        http://{ip}:{port}")
        print("   ※ 휴대폰은 Wi-Fi에 연결하고, 그 Wi-Fi와 같은 대역의 주소를 쓰세요.")
        print("   ※ 윈도우 방화벽에서 해당 포트 인바운드 허용이 필요할 수 있습니다.")
        print("   종료: Ctrl + C")
        print("=" * 60)

    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=8)
    except ImportError:
        print("[알림] waitress 미설치 — 개발 서버로 실행합니다. "
              "운영 시 'pip install waitress' 후 다시 실행하세요.")
        app.run(host=host, port=port, debug=False)
