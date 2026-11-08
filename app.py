"""Course Registration System - application factory and entry point."""
import logging
import os
import secrets

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, session, url_for
from werkzeug.exceptions import HTTPException

import database
import navigation
import security

load_dotenv()

_PLACEHOLDER_SECRETS = {"", "replace_with_a_long_random_secret", "change-this-development-secret"}


def create_app(test_config=None):
    app = Flask(__name__)

    secret = os.getenv("FLASK_SECRET_KEY", "")
    if secret in _PLACEHOLDER_SECRETS:
        secret = secrets.token_hex(32)
        logging.getLogger(__name__).warning(
            "FLASK_SECRET_KEY is not set; using a random key. "
            "Users will be signed out whenever the server restarts. Set it in .env."
        )
    app.config.update(
        SECRET_KEY=secret,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("FLASK_SECURE_COOKIES", "0") == "1",
        PERMANENT_SESSION_LIFETIME=int(os.getenv("SESSION_LIFETIME_MINUTES", "120")) * 60,
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    # --- database lifecycle, CSRF, template helpers -----------------------
    app.teardown_appcontext(database.close_db)
    app.before_request(security.validate_csrf)
    app.jinja_env.globals["csrf_token"] = security.csrf_token

    @app.context_processor
    def inject_user():
        return {
            "current_role": session.get("role"),
            "current_user_name": session.get("user_name"),
            "nav_groups": navigation.NAV.get(session.get("role"), []),
        }

    @app.after_request
    def secure_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'"
        )
        if session.get("role"):
            # signed-in pages must not be served from cache after logout
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # --- blueprints -------------------------------------------------------
    from blueprints.auth import bp as auth_bp
    from blueprints.admin import bp as admin_bp
    from blueprints.faculty import bp as faculty_bp
    from blueprints.student import bp as student_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(faculty_bp)
    app.register_blueprint(student_bp)

    # --- home & errors ----------------------------------------------------
    @app.route("/")
    def home():
        role = session.get("role")
        if role in security.ROLES:
            return redirect(url_for(f"{role}.dashboard"))
        return render_template("index.html")

    @app.errorhandler(HTTPException)
    def http_error(err):
        messages = {
            400: "The request could not be processed.",
            403: "You do not have permission to open this page.",
            404: "The page you asked for does not exist.",
            405: "That action is not allowed here.",
            413: "The submitted data is too large.",
        }
        message = err.description if err.code == 400 and err.description else messages.get(
            err.code, "Something went wrong.")
        return render_template("error.html", code=err.code, message=message), err.code

    @app.errorhandler(Exception)
    def unexpected_error(err):
        app.logger.exception("Unhandled error")
        return render_template("error.html", code=500,
                               message="An unexpected error occurred. Please try again."), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
