"""실행 진입점.

    python run.py                # 개발 서버 실행 (http://127.0.0.1:5000)
    flask --app run.py init-db   # DB 초기화
    flask --app run.py seed      # 합성/데모 시드 적재
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
