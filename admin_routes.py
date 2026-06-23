from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, request
from flask_login import login_required, current_user

from web.models import db, User


admin_bp = Blueprint("admin", __name__)


def is_admin():

    return (
        current_user.is_authenticated
        and current_user.role == "Admin"
    )


def is_security_user():

    return (
        current_user.is_authenticated
        and current_user.role in ["Admin", "Security Analyst"]
    )


def admin_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not is_admin():

            return render_template("access_denied.html")

        return function(*args, **kwargs)

    return wrapper


def security_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not is_security_user():

            return render_template("access_denied.html")

        return function(*args, **kwargs)

    return wrapper


@admin_bp.route("/users")
@login_required
@admin_required
def users():

    all_users = User.query.order_by(User.id.asc()).all()

    return render_template(
        "users.html",
        users=all_users
    )


@admin_bp.route("/update-role", methods=["POST"])
@login_required
@admin_required
def update_role():

    user_id = request.form.get("user_id")

    new_role = request.form.get("role")

    allowed_roles = [
        "Employee",
        "Security Analyst",
        "Admin"
    ]

    if new_role not in allowed_roles:

        return redirect(url_for("admin.users"))

    user = User.query.get(int(user_id))

    if user:

        user.role = new_role

        db.session.commit()

    return redirect(url_for("admin.users"))
