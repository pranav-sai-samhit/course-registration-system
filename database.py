"""PostgreSQL access layer.

* One connection per request, stored on ``flask.g`` and closed automatically.
* Every request runs inside a transaction. Views call ``commit()`` explicitly;
  anything not committed is rolled back when the request ends, so a failed
  multi-step operation can never leave partial data behind.
* All SQL is parameterised (``%s`` placeholders). Never build SQL with string
  formatting of user input.
"""
import os

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from flask import g

load_dotenv()


def get_db_connection():
    """Open a new standalone connection (used by scripts and tests)."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "CourseRegistrationDB"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "5")),
    )


def get_db():
    """Return this request's connection, opening it on first use."""
    if "db" not in g:
        g.db = get_db_connection()
    return g.db


def close_db(exc=None):
    """Teardown hook: roll back anything uncommitted, then close."""
    conn = g.pop("db", None)
    if conn is not None:
        try:
            conn.rollback()
        finally:
            conn.close()


def _cursor():
    return get_db().cursor(cursor_factory=RealDictCursor)


def query_all(sql, params=()):
    with _cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_one(sql, params=()):
    with _cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql, params=()):
    """Run INSERT/UPDATE/DELETE. Returns the affected row count."""
    with _cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def next_id(table, id_column):
    """Next integer primary key.

    The schema's primary keys have no serial/identity default, so IDs are
    generated here. The table is locked for the rest of the transaction so
    two concurrent inserts cannot pick the same MAX()+1 value.
    Table/column names come from code, never from user input.
    """
    allowed = {
        "admin": "admin_id", "program": "program_id", "department": "department_id",
        "semester": "semester_id", "student": "student_id", "faculty": "faculty_id",
        "course": "course_id", "course_registration": "registration_id",
        "faculty_assignment": "assignment_id", "passing_mark_approval": "approval_id",
    }
    if allowed.get(table) != id_column:
        raise ValueError("Unknown table/column for ID generation.")
    with _cursor() as cur:
        cur.execute(f"LOCK TABLE public.{table} IN EXCLUSIVE MODE")
        cur.execute(f"SELECT COALESCE(MAX({id_column}), 0) + 1 AS next_id FROM public.{table}")
        return cur.fetchone()["next_id"]


def commit():
    get_db().commit()


def rollback():
    conn = g.get("db")      # do not open a new connection just to roll back
    if conn is not None:
        conn.rollback()
