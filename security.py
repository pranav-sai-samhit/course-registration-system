"""Sessions, role-based access control, CSRF protection and password helpers."""
import hmac
import secrets
from functools import wraps

from flask import abort, flash, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

ROLES = ("admin", "faculty", "student")
HASH_PREFIXES = ("scrypt:", "pbkdf2:")

# A real hash used to burn the same CPU time when an email is not found,
# so response timing does not reveal which emails exist.
_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))


# ---------------------------------------------------------------- passwords
def hash_password(password):
    return generate_password_hash(password)


def is_hashed(value):
    return bool(value) and value.startswith(HASH_PREFIXES)


def verify_password(stored, supplied):
    """Return ``(is_valid, needs_upgrade)``.

    ``needs_upgrade`` is True when the stored value is a legacy plain-text
    password that matched; the caller should then store a proper hash.
    """
    if not stored:
        check_password_hash(_DUMMY_HASH, supplied or "")
        return False, False
    if is_hashed(stored):
        return check_password_hash(stored, supplied or ""), False
    ok = hmac.compare_digest(stored.encode(), (supplied or "").encode())
    return ok, ok


def check_password_strength(password):
    """Return an error message, or None when the password is acceptable."""
    if len(password or "") < 8:
        return "Password must be at least 8 characters long."
    return None


# ----------------------------------------------------------------- sessions
def login_user(role, user_id, name):
    session.clear()           # drops any previous role / prevents session fixation
    session.permanent = True
    session["role"] = role
    session["user_id"] = user_id
    session["user_name"] = name
    session["csrf_token"] = secrets.token_urlsafe(32)


def current_role():
    return session.get("role")


def current_user_id():
    return session.get("user_id")


def role_required(role):
    """Allow only the given role.

    * Not signed in           -> redirect to that role's login page.
    * Signed in as another role -> 403 (no cross-role access).
    """
    if role not in ROLES:
        raise ValueError(role)

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            actual = session.get("role")
            if actual is None or not session.get("user_id"):
                flash("Please sign in to continue.", "warning")
                return redirect(url_for(f"auth.{role}_login"))
            if actual != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


# --------------------------------------------------------------------- CSRF
def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def validate_csrf():
    """Reject state-changing requests that lack a valid token."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
    expected = session.get("csrf_token", "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, description="Your form session expired. Reload the page and try again.")
