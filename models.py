from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from sqlalchemy import text


db = SQLAlchemy()

login_manager = LoginManager()
login_manager.login_view = "auth.login"


class User(UserMixin, db.Model):

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(100), unique=True, nullable=False)

    email = db.Column(db.String(150), unique=True, nullable=False)

    password_hash = db.Column(db.String(255), nullable=False)

    smtp_email = db.Column(db.String(150), nullable=False)

    smtp_password = db.Column(db.String(255), nullable=False)

    role = db.Column(db.String(50), nullable=False, default="Employee")


class EmailIncident(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    sender = db.Column(db.String(150), nullable=False)

    recipient = db.Column(db.String(150), nullable=False)

    filename = db.Column(db.String(255), nullable=False)

    classification = db.Column(db.String(50), nullable=False)

    action = db.Column(db.String(50), nullable=False)

    confidence = db.Column(db.String(50), nullable=False)

    timestamp = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )


@login_manager.user_loader
def load_user(user_id):

    return User.query.get(int(user_id))


def ensure_database_schema():

    db.create_all()

    try:
        result = db.session.execute(text("PRAGMA table_info(user)"))

        columns = [row[1] for row in result.fetchall()]

        if "role" not in columns:

            db.session.execute(
                text(
                    "ALTER TABLE user "
                    "ADD COLUMN role VARCHAR(50) "
                    "NOT NULL DEFAULT 'Employee'"
                )
            )

            db.session.commit()

    except Exception as e:
        print(f"[DB SCHEMA WARNING] {e}")

    try:
        admin_exists = User.query.filter_by(role="Admin").first()

        first_user = User.query.order_by(User.id.asc()).first()

        if first_user and not admin_exists:

            first_user.role = "Admin"

            db.session.commit()

            print(
                f"[ACCESS CONTROL] "
                f"User {first_user.username} promoted to Admin."
            )

    except Exception as e:
        print(f"[ROLE INIT WARNING] {e}")
