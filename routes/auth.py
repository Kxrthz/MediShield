from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from urllib.parse import urljoin, urlparse

from extensions import db
from models import User

auth_bp = Blueprint("auth", __name__)


def safe_next_url(target):
    if not target:
        return None
    ref = urlparse(urljoin(request.host_url, target))
    return target if ref.scheme in ("http", "https") and ref.netloc == request.host else None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("page_dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user:
            flash("Email not found. Check your address or contact your administrator.", "error")
        elif not user.check_password(password):
            flash("Incorrect password. Please try again.", "error")
        else:
            login_user(user, remember=request.form.get("remember") == "on")
            return redirect(safe_next_url(request.args.get("next")) or url_for("page_dashboard"))
    return render_template("login.html", page_title="Sign in")


@auth_bp.post("/logout")
def logout():
    logout_user()
    flash("You have signed out.", "success")
    return redirect(url_for("auth.login"))
