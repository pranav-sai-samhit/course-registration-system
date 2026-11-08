# Course Registration System

Flask + PostgreSQL (psycopg2) + Bootstrap. Three roles: Admin, Faculty, Student. Uses your existing `CourseRegistrationDB` with exactly 10 tables; the application never creates, drops or alters tables.

## 1. Install

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure `.env`

Copy `.env.example` to `.env` and fill in your PostgreSQL password and a secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Never commit `.env`. Database name stays `CourseRegistrationDB`.

## 3. Check the database (optional, read-only)

Open `sql/verify_schema.sql` in pgAdmin's Query Tool and run it. No migration is required for the schema you provided. The app only reads/writes rows.

## 4. Run

```bash
python app.py
```

Open http://127.0.0.1:5000 and pick a portal. Each role has its own login page.

## 5. Accounts (no default credentials exist)

Passwords are stored hashed. Create or reset an account securely:

```bash
python scripts/set_password.py admin you@example.edu --create --name "Your Name"
python scripts/set_password.py faculty someone@example.edu
python scripts/set_password.py student someone@example.edu
```

An existing plain-text value in `admin.password` is upgraded to a hash at that admin's first login.

## 6. Main features

**Admin** – Students, Faculty, Programs, Departments, Semesters, Courses, Course Registrations, Faculty Assignments, Passing Mark Approvals.

**Faculty** – My Assigned Courses, My Assigned Students, Marks Entry, Student Results, Passing Mark Requests.

**Student** – My Profile, Available Courses, My Registered Courses, My Marks, My Results.

## 7. Rules worth knowing

- No passing mark is needed to register. It is needed to save marks; it is copied into `course_registration.passing_mark_used` at that moment.
- Every reattempt is a new `course_registration` row. Cancelled rows stay in history.
- Student-level assignment rows store the registration's own semester.
- Faculty enter marks once; corrections are an admin action.

## 8. Tests

Install development dependencies:

```bash
pip install -r requirements-dev.txt
```

Create an empty database whose name ends in `_test` (e.g. `CourseRegistrationDB_test`), configure `DB_NAME`, `DB_USER`, and `DB_PASSWORD` for it, then run:

```bash
pytest
```

The suite wipes that database; it refuses to run if the name does not end in `_test`. Never point it at your real database.