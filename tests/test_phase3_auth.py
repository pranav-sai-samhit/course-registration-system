"""Phase 3: authentication, sessions, role isolation, CSRF, DB layer (live PostgreSQL)."""
import importlib.util
import pathlib
import sys

import pytest

import database as db
import security
from conftest import PASSWORD, ROOT, _exec, get_csrf

ACCOUNTS = {"admin": "admin@test.edu", "faculty": "fay@test.edu", "student": "sam@test.edu"}


# ------------------------------------------------------------------ schema
def test_database_has_exactly_ten_tables(seeded):
    conn = db.get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1")
            names = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    assert names == sorted(["admin", "program", "department", "semester", "student", "faculty",
                            "course", "course_registration", "faculty_assignment",
                            "passing_mark_approval"])


# ------------------------------------------------------------------- pages
def test_home_shows_portal_chooser(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Administrator" in r.data and b"Faculty" in r.data


@pytest.mark.parametrize("role", ACCOUNTS)
def test_login_pages_render(client, role):
    r = client.get(f"/{role}/login")
    assert r.status_code == 200 and b"csrf_token" in r.data


def test_unknown_page_gives_friendly_404(client):
    r = client.get("/nope")
    assert r.status_code == 404 and b"does not exist" in r.data


# ------------------------------------------------------------------- login
@pytest.mark.parametrize("role,email", ACCOUNTS.items())
def test_login_redirects_to_own_dashboard(client, login, role, email):
    r = login(role, email)
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/{role}/dashboard")
    page = client.get(f"/{role}/dashboard")
    assert page.status_code == 200
    # home now redirects signed-in users to their dashboard
    assert client.get("/").headers["Location"].endswith(f"/{role}/dashboard")


def test_email_is_case_insensitive(client, login):
    assert login("student", "SAM@Test.EDU").status_code == 302


@pytest.mark.parametrize("role,email", ACCOUNTS.items())
def test_wrong_password_rejected(client, login, role, email):
    r = login(role, email, "wrong-password")
    assert r.status_code == 401 and b"Invalid email or password" in r.data
    assert client.get(f"/{role}/dashboard").status_code == 302      # still signed out


def test_unknown_email_gives_same_message(client, login):
    r = login("student", "nobody@test.edu")
    assert r.status_code == 401 and b"Invalid email or password" in r.data


def test_empty_fields_rejected(client, login):
    r = login("admin", "", "")
    assert r.status_code == 400 and b"Enter both email and password" in r.data


def test_account_cannot_log_in_through_other_role_portal(client, login):
    # a student's credentials must not work on the admin/faculty login pages
    assert login("admin", "sam@test.edu").status_code == 401
    assert login("faculty", "sam@test.edu").status_code == 401


def test_passwords_are_stored_hashed(seeded):
    for table, col in (("admin", "password"), ("faculty", "password_hash"), ("student", "password_hash")):
        conn = db.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {col} FROM {table}")
                assert all(security.is_hashed(r[0]) for r in cur.fetchall())
        finally:
            conn.close()


def test_legacy_plaintext_password_is_upgraded_on_login(client, login):
    _exec("UPDATE student SET password_hash='plain-secret' WHERE student_id=2")
    assert login("student", "sue@test.edu", "plain-secret").status_code == 302
    conn = db.get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM student WHERE student_id=2")
            stored = cur.fetchone()[0]
    finally:
        conn.close()
    assert security.is_hashed(stored) and stored != "plain-secret"


def test_wrong_legacy_plaintext_password_not_upgraded(client, login):
    _exec("UPDATE student SET password_hash='plain-secret' WHERE student_id=2")
    assert login("student", "sue@test.edu", "guess").status_code == 401
    conn = db.get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM student WHERE student_id=2")
            assert cur.fetchone()[0] == "plain-secret"
    finally:
        conn.close()


def test_sql_injection_attempt_in_email_is_harmless(client, login):
    r = login("admin", "' OR '1'='1' --", "x")
    assert r.status_code == 401
    r = login("admin", "admin@test.edu'; DROP TABLE admin; --", "x")
    assert r.status_code == 401
    assert login("admin", "admin@test.edu").status_code == 302      # table still there


# --------------------------------------------------------- role isolation
@pytest.mark.parametrize("role", ACCOUNTS)
def test_anonymous_redirected_to_login(client, role):
    r = client.get(f"/{role}/dashboard")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/{role}/login")


@pytest.mark.parametrize("role,email", ACCOUNTS.items())
def test_users_cannot_open_other_roles_dashboards(client, login, role, email):
    login(role, email)
    for other in ACCOUNTS:
        expected = 200 if other == role else 403
        assert client.get(f"/{other}/dashboard").status_code == expected


# --------------------------------------------------------- logout / CSRF
def test_logout_requires_post_and_clears_session(client, login):
    login("student", "sam@test.edu")
    assert client.get("/logout").status_code == 405
    token = get_csrf(client, "/student/dashboard")
    r = client.post("/logout", data={"csrf_token": token})
    assert r.status_code == 302 and r.headers["Location"].endswith("/student/login")
    assert client.get("/student/dashboard").status_code == 302


def test_post_without_csrf_token_is_rejected(client):
    r = client.post("/student/login", data={"email": "sam@test.edu", "password": PASSWORD})
    assert r.status_code == 400
    r = client.post("/student/login", data={"email": "sam@test.edu", "password": PASSWORD,
                                            "csrf_token": "forged"})
    assert r.status_code == 400


def test_logout_without_csrf_token_is_rejected(client, login):
    login("admin", "admin@test.edu")
    assert client.post("/logout").status_code == 400
    assert client.get("/admin/dashboard").status_code == 200        # still signed in


def test_csrf_token_changes_on_login(client, login):
    before = get_csrf(client, "/student/login")
    login("student", "sam@test.edu")
    after = get_csrf(client, "/student/dashboard")
    assert before != after


# ------------------------------------------------------ headers / cookies
def test_security_headers_and_no_store(client, login):
    r = client.get("/student/login")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    login("student", "sam@test.edu")
    assert client.get("/student/dashboard").headers["Cache-Control"] == "no-store"


def test_session_cookie_flags(client, login):
    r = login("student", "sam@test.edu")
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_bootstrap_is_served_locally(client):
    assert client.get("/static/vendor/bootstrap/css/bootstrap.min.css").status_code == 200
    assert client.get("/static/vendor/bootstrap/js/bootstrap.bundle.min.js").status_code == 200


# --------------------------------------------------------------- DB layer
def test_database_outage_shows_friendly_error(client, login, monkeypatch):
    monkeypatch.setenv("DB_PORT", "1")          # nothing listens here
    r = login("student", "sam@test.edu")
    assert r.status_code == 503 and b"Could not reach the database" in r.data


def test_uncommitted_changes_are_rolled_back(app):
    with app.app_context():
        db.execute("INSERT INTO program VALUES (99,'Temp','Temp',1)")
        assert db.query_one("SELECT 1 FROM program WHERE program_id=99")   # visible in-transaction
    with app.app_context():
        assert db.query_one("SELECT 1 FROM program WHERE program_id=99") is None


def test_committed_changes_persist(app):
    with app.app_context():
        db.execute("INSERT INTO program VALUES (98,'Kept','Kept',1)")
        db.commit()
    with app.app_context():
        assert db.query_one("SELECT program_name FROM program WHERE program_id=98")["program_name"] == "Kept"


def test_next_id_and_whitelist(app):
    with app.app_context():
        assert db.next_id("program", "program_id") == 2
        with pytest.raises(ValueError):
            db.next_id("program; DROP TABLE admin", "program_id")


# ------------------------------------------------------- password helpers
def test_password_strength_rule():
    assert security.check_password_strength("short") is not None
    assert security.check_password_strength("long-enough-1") is None


def test_set_password_script(seeded, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("set_password", ROOT / "scripts" / "set_password.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def run(argv, *passwords):
        answers = iter(passwords)
        monkeypatch.setattr(mod.getpass, "getpass", lambda prompt="": next(answers))
        monkeypatch.setattr(sys, "argv", ["set_password.py", *argv])
        mod.main()

    run(["student", "sam@test.edu"], "Brand-New-Pass-9", "Brand-New-Pass-9")
    run(["admin", "root@test.edu", "--create", "--name", "Root Admin"], "Another-Pass-77", "Another-Pass-77")
    with pytest.raises(SystemExit):                       # mismatch
        run(["student", "sam@test.edu"], "Aaaaaaaa1", "Bbbbbbbb2")
    with pytest.raises(SystemExit):                       # too short
        run(["student", "sam@test.edu"], "short", "short")
    with pytest.raises(SystemExit):                       # unknown account
        run(["student", "ghost@test.edu"], "Valid-Pass-123", "Valid-Pass-123")

    from app import create_app
    c = create_app({"TESTING": True}).test_client()

    def attempt(role, email, pw):
        tok = get_csrf(c, f"/{role}/login")
        return c.post(f"/{role}/login", data={"email": email, "password": pw, "csrf_token": tok}).status_code

    assert attempt("student", "sam@test.edu", "Brand-New-Pass-9") == 302
    c.post("/logout", data={"csrf_token": get_csrf(c, "/student/dashboard")})
    assert attempt("student", "sam@test.edu", PASSWORD) == 401         # old password gone
    assert attempt("admin", "root@test.edu", "Another-Pass-77") == 302
