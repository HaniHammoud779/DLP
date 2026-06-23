from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_user, logout_user, login_required

from werkzeug.security import generate_password_hash, check_password_hash

from web.models import db, User


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def index():

    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():

    message = ""

    if request.method == "POST":

        username = request.form["username"].strip()
        email = request.form["email"].strip()
        password = request.form["password"]
        smtp_email = request.form["smtp_email"].strip()
        smtp_password = request.form["smtp_password"].strip()

        existing_user = User.query.filter(
            (User.username == username) |
            (User.email == email)
        ).first()

        if existing_user:

            message = "User already exists."

        else:

            user_count = User.query.count()

            assigned_role = "Admin" if user_count == 0 else "Employee"

            new_user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                smtp_email=smtp_email,
                smtp_password=smtp_password,
                role=assigned_role
            )

            db.session.add(new_user)
            db.session.commit()

            login_user(new_user)

            return redirect(url_for("email.compose"))

    return render_template(
        "register.html",
        message=message
    )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    message = ""

    if request.method == "POST":

        username = request.form["username"].strip()
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):

            login_user(user)

            return redirect(url_for("email.compose"))

        message = "Invalid username or password."

    return render_template(
        "login.html",
        message=message
    )


@auth_bp.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(url_for("auth.login"))
