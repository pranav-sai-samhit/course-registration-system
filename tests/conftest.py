"""Test fixtures. Runs ONLY against a throwaway database whose name ends in _test."""
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "CourseRegistrationDB_test")
os.environ.setdefault("DB_USER", "crs_test")
os.environ.setdefault("DB_PASSWORD", "crs_test_pw")
os.environ["FLASK_SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"

if not os.environ["DB_NAME"].endswith("_test"):
    raise SystemExit("Refusing to run tests: DB_NAME must end with '_test' (tests wipe the database).")

import database  # noqa: E402
import security  # noqa: E402
from app import create_app  # noqa: E402

PASSWORD = "Test-Pass-123"


def _exec(sql, params=()):
    conn = database.get_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
    finally:
        conn.close()


@pytest.fixture(scope="session", autouse=True)
def schema():
    _exec("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    _exec((ROOT / "tests" / "schema_test.sql").read_text())


@pytest.fixture()
def seeded(schema):
    """Fresh minimal data for each test: 1 admin, 2 faculty, 2 students."""
    _exec("""TRUNCATE passing_mark_approval, faculty_assignment, course_registration, course,
             student, faculty, semester, department, program, admin RESTART IDENTITY CASCADE""")
    h = security.hash_password(PASSWORD)
    _exec("INSERT INTO admin VALUES (1,'Ada Admin','admin@test.edu',%s)", (h,))
    _exec("INSERT INTO program VALUES (1,'B.Tech','B.Tech',4)")
    _exec("INSERT INTO department VALUES (1,'CSE',1)")
    _exec("INSERT INTO semester VALUES (1,1,1,1),(2,1,2,1),(3,1,3,2)")
    _exec("INSERT INTO faculty VALUES (1,'Fay Faculty','fay@test.edu',%s),(2,'Fred Faculty','fred@test.edu',%s)", (h, h))
    _exec("INSERT INTO student VALUES (1,'Sam Student','sam@test.edu',%s,1,1,1),(2,'Sue Student','sue@test.edu',%s,1,1,1)", (h, h))


@pytest.fixture()
def app(seeded):
    return create_app({"TESTING": True})


@pytest.fixture()
def client(app):
    return app.test_client()


def get_csrf(client, path):
    html = client.get(path).get_data(as_text=True)
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start:html.index('"', start)]


@pytest.fixture()
def login(client):
    def _login(role, email, password=PASSWORD):
        token = get_csrf(client, f"/{role}/login")
        return client.post(f"/{role}/login",
                           data={"email": email, "password": password, "csrf_token": token})
    return _login
