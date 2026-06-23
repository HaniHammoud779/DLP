import os
import sys

from flask import Flask

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from web.models import db, login_manager, ensure_database_schema
from web.auth_routes import auth_bp
from web.email_routes import email_bp
from web.dashboard_routes import dashboard_bp
from web.admin_routes import admin_bp
from web.approval_routes import approval_bp


def create_app():

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )

    app.config["SECRET_KEY"] = "enterprise-dlp-secret-key"

    database_path = os.path.join(
        PROJECT_DIR,
        "enterprise_mail_users.db"
    )

    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{database_path}"

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(email_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(approval_bp)

    with app.app_context():
        ensure_database_schema()

    return app


app = create_app()


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
