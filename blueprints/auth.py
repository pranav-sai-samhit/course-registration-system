"""Login and logout for the three roles."""
import psycopg2
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

import database as db
import security

bp = Blueprint("auth", __name__)

# Table and column names are fixed constants (never user input).
ROLE_TABLES = {
    "admin":   {"table": "admin",   "id": "admin_id",   "secret": "password",      "label": "Administrator"},
    "faculty": {"table": "faculty", "id": "faculty_id", "secret": "password_hash", "label": "Faculty"},
    "student": {"table": "student", "id": "student_id", "secret": "password_hash", "label": "Student"},
}


def _attempt_login(role):
    cfg = ROLE_TABLES[role]

    if session.get("role") in security.ROLES:
        return redirect(url_for(f"{session['role']}.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Enter both email and password.", "error")
            return render_template("login.html", role=role, label=cfg["label"], email=email), 400
        try:
            account = db.query_one(
                f"SELECT {cfg['id']} AS user_id, name, {cfg['secret']} AS secret "
                f"FROM {cfg['table']} WHERE LOWER(email) = %s", (email,))
            valid, upgrade = security.verify_password(account["secret"] if account else None, password)
            if not (account and valid):
                flash("Invalid email or password.", "error")
                return render_template("login.html", role=role, label=cfg["label"], email=email), 401
            if upgrade:   # legacy plain-text password -> store a secure hash
                db.execute(
                    f"UPDATE {cfg['table']} SET {cfg['secret']} = %s WHERE {cfg['id']} = %s",
                    (security.hash_password(password), account["user_id"]))
                db.commit()
        except psycopg2.Error:
            db.rollback()
            current_app.logger.exception("Database error during %s login", role)
            flash("Could not reach the database. Check the connection settings and try again.", "error")
            return render_template("login.html", role=role, label=cfg["label"], email=email), 503

        security.login_user(role, account["user_id"], account["name"])
        return redirect(url_for(f"{role}.dashboard"))

    return render_template("login.html", role=role, label=cfg["label"], email="")


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    return _attempt_login("admin")


@bp.route("/faculty/login", methods=["GET", "POST"])
def faculty_login():
    return _attempt_login("faculty")


@bp.route("/student/login", methods=["GET", "POST"])
def student_login():
    return _attempt_login("student")


@bp.route("/logout", methods=["POST"])
def logout():
    role = session.get("role")
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for(f"auth.{role}_login") if role in security.ROLES else url_for("home"))
