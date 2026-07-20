"""Flask 애플리케이션 팩토리."""
import click
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "로그인이 필요합니다."


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # 블루프린트 등록
    from .routes.auth import bp as auth_bp
    from .routes.dashboard import bp as dash_bp
    from .routes.master import bp as master_bp
    from .routes.qc import bp as qc_bp
    from .routes.review import bp as review_bp
    from .routes.capa import bp as capa_bp
    from .routes.audit import bp as audit_bp
    from .routes.account import bp as account_bp
    from .routes.phrase import bp as phrase_bp
    from .routes.settings import bp as settings_bp
    from .routes.admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(phrase_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(admin_bp)

    # 문서 메타데이터를 모든 템플릿에서 사용할 수 있도록 주입
    from .models import DocumentMeta

    @app.context_processor
    def inject_doc_meta():
        try:
            return {"doc_meta": DocumentMeta.query.get(1)}
        except Exception:
            return {"doc_meta": None}
    app.register_blueprint(dash_bp)
    app.register_blueprint(master_bp)
    app.register_blueprint(qc_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(capa_bp)
    app.register_blueprint(audit_bp)

    # 템플릿 전역 필터
    from .westgard import RULE_INFO

    @app.template_filter("rulename")
    def rulename(code):
        return RULE_INFO.get(code, (code,))[0]

    # ------------------------------------------------------------------ CLI
    @app.cli.command("init-db")
    def init_db():
        """DB 스키마 생성."""
        db.create_all()
        click.echo("DB 초기화 완료.")

    @app.cli.command("seed")
    def seed_cmd():
        """데모/합성 시드 데이터 적재."""
        from .seed import run_seed
        db.create_all()
        run_seed()
        click.echo("시드 적재 완료.")

    return app
