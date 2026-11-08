# Course Registration System

Flask + PostgreSQL (psycopg2) + Bootstrap. Three roles: Admin, Faculty, Student. Uses your existing
`CourseRegistrationDB` with exactly 10 tables; the application never creates, drops or alters tables.

## 1. Install
```
python -m venv venv
venv\Scripts\activate            (Windows)   |   source venv/bin/activate   (macOS/Linux)
pip install -r requirements.txt
```

## 2. Configure `.env`
Copy `.env.example` to `.env` and fill in your PostgreSQL password and a secret key
(`python -c "import secrets; print(secrets.token_hex(32))"`). Never commit `.env`.
Database name stays `CourseRegistrationDB`.

## 3. Check the database (optional, read-only)
Open `sql/verify_schema.sql` in pgAdmin's Query Tool and run it. No migration is required for the
schema you provided. The app only reads/writes rows.

## 4. Run
```
python app.py
```
Open http://127.0.0.1:5000 and pick a portal. Each role has its own login page.

## 5. Accounts (no default credentials exist)
Passwords are stored hashed. Create or reset an account securely (the password is typed at a hidden prompt):
```
python scripts/set_password.py admin you@example.edu --create --name "Your Name"
python scripts/set_password.py faculty someone@example.edu
python scripts/set_password.py student someone@example.edu
```
An existing plain-text value in `admin.password` is upgraded to a hash at that admin's first login.
After that the admin can create students and faculty on the Students / Faculty pages.

## 6. Main features
**Admin** – Students, Faculty, Programs, Departments, Semesters, Courses (CRUD with referential-integrity
checks); Course Registrations (create, cancel, restore, correct marks); Faculty Assignments
(course-level: program → department → academic year → semester → course → faculty; student-level:
student → registration → faculty already on that course); Passing Mark Approvals (approve / reject
proposals, set a mark directly; everything is logged in `passing_mark_approval`).

**Faculty** – My Assigned Courses, My Assigned Students (only registrations assigned to you), Marks Entry
(once per attempt, needs an official passing mark), Student Results, Passing Mark Requests (propose, edit
your own pending proposal, see status).

**Student** – My Profile, Available Courses (register for current-semester courses; reattempt failed ones
in a later semester; max 2 electives per semester), My Registered Courses (all attempts), My Marks, My Results
(latest attempt decides; earlier attempts stay visible).

## 7. Rules worth knowing
* No passing mark is needed to register. It is needed to save marks; it is copied into
  `course_registration.passing_mark_used` at that moment, so later changes never alter old results.
* Every reattempt is a new `course_registration` row. Cancelled rows stay in history; they are cancelled/restored, not deleted.
* Student-level assignment rows store the registration's own semester (a reattempt in a later semester is its own row).
* Proposal rows: faculty proposal = `faculty_id` set, `faculty_status='APPROVED'` (submitted), `admin_status='PENDING'`;
  admin-initiated change = `faculty_id` NULL, both statuses `APPROVED`. `approval_date` is the decision date.
* Faculty enter marks once; corrections are an admin action and keep the stored passing mark.

## 8. Tests
`pip install -r requirements-dev.txt`, create an empty database whose name ends in `_test`
(e.g. `CourseRegistrationDB_test`) and set `DB_NAME`, `DB_USER`, `DB_PASSWORD` for it, then `pytest`.
The suite wipes that database; it refuses to run if the name does not end in `_test`. Never point it at your real database.
