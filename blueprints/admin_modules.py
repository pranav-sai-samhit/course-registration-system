"""Definitions of the six admin CRUD modules: form fields, list queries and validation.

Each module's ``clean(form, record_id)`` returns the column values to store (validated)
or raises ValueError with a message for the admin. ``record_id`` is None when creating.
"""
import database as db
import passing_marks
import security
import validators as v


# ------------------------------------------------------------------ helpers
def _count(sql, params):
    return db.query_one(sql, params)["n"]


def _same_program(department_id, semester_id, program_id):
    row = db.query_one("""
        SELECT d.program_id AS dept_program, se.program_id AS sem_program
        FROM department d CROSS JOIN semester se
        WHERE d.department_id = %s AND se.semester_id = %s""", (department_id, semester_id))
    return bool(row) and row["dept_program"] == program_id and row["sem_program"] == program_id


def _password_hash(form, record_id):
    raw = form.get("password", "")
    if not raw:
        if record_id is None:
            raise ValueError("Password is required when creating an account.")
        return None
    problem = security.check_password_strength(raw)
    if problem:
        raise ValueError(problem)
    return security.hash_password(raw)


def _existing(table, pk, record_id):
    row = db.query_one(f"SELECT * FROM {table} WHERE {pk} = %s", (record_id,))   # constants only
    if not row:
        raise ValueError("Record not found.")
    return row


# ------------------------------------------------------------------ cleaners
def clean_student(form, record_id):
    values = {
        "name": v.text(form.get("name"), "Student name", 100),
        "email": v.email(form.get("email")),
        "program_id": v.choice_id(form.get("program_id"), "Program"),
        "department_id": v.choice_id(form.get("department_id"), "Department"),
        "current_semester_id": v.choice_id(form.get("current_semester_id"), "Current semester"),
    }
    if not _same_program(values["department_id"], values["current_semester_id"], values["program_id"]):
        raise ValueError("The student's program, department and current semester must all belong to the same program.")
    if _count("SELECT COUNT(*) AS n FROM student WHERE LOWER(email) = %s AND student_id <> %s",
              (values["email"], record_id or -1)):
        raise ValueError("Another student already uses this email address.")
    if record_id is not None:
        old = _existing("student", "student_id", record_id)
        moved = (old["program_id"], old["department_id"]) != (values["program_id"], values["department_id"])
        if moved and _count("SELECT COUNT(*) AS n FROM course_registration WHERE student_id = %s", (record_id,)):
            raise ValueError("This student has course registrations, so program and department cannot be changed. "
                             "Only the current semester can be changed.")
    hashed = _password_hash(form, record_id)
    if hashed:
        values["password_hash"] = hashed
    return values


def clean_faculty(form, record_id):
    values = {
        "name": v.text(form.get("name"), "Faculty name", 100),
        "email": v.email(form.get("email")),
    }
    if _count("SELECT COUNT(*) AS n FROM faculty WHERE LOWER(email) = %s AND faculty_id <> %s",
              (values["email"], record_id or -1)):
        raise ValueError("Another faculty member already uses this email address.")
    hashed = _password_hash(form, record_id)
    if hashed:
        values["password_hash"] = hashed
    return values


def clean_program(form, record_id):
    values = {
        "program_name": v.text(form.get("program_name"), "Program name", 100),
        "program_type": v.text(form.get("program_type"), "Program type", 50),
        "duration_years": v.integer(form.get("duration_years"), "Duration (years)", 1, 15),
    }
    if _count("SELECT COUNT(*) AS n FROM program WHERE LOWER(program_name) = LOWER(%s) AND program_id <> %s",
              (values["program_name"], record_id or -1)):
        raise ValueError("A program with this name already exists.")
    if record_id is not None:
        longest = db.query_one("SELECT COALESCE(MAX(semester_number), 0) AS n FROM semester WHERE program_id = %s",
                               (record_id,))["n"]
        if values["duration_years"] * 2 < longest:
            raise ValueError(f"The program already has a semester numbered {longest}; "
                             f"a duration of {values['duration_years']} years is too short.")
    return values


def clean_department(form, record_id):
    values = {
        "department_name": v.text(form.get("department_name"), "Department name", 100),
        "program_id": v.choice_id(form.get("program_id"), "Program"),
    }
    if not db.query_one("SELECT 1 AS ok FROM program WHERE program_id = %s", (values["program_id"],)):
        raise ValueError("Select a valid program.")
    if _count("""SELECT COUNT(*) AS n FROM department
                 WHERE LOWER(department_name) = LOWER(%s) AND program_id = %s AND department_id <> %s""",
              (values["department_name"], values["program_id"], record_id or -1)):
        raise ValueError("This program already has a department with that name.")
    if record_id is not None:
        old = _existing("department", "department_id", record_id)
        if old["program_id"] != values["program_id"]:
            linked = _count("""SELECT (SELECT COUNT(*) FROM student WHERE department_id = %(d)s)
                                    + (SELECT COUNT(*) FROM course WHERE department_id = %(d)s) AS n""",
                            {"d": record_id})
            if linked:
                raise ValueError("This department has students or courses, so it cannot be moved to another program.")
    return values


def clean_semester(form, record_id):
    program_id = v.choice_id(form.get("program_id"), "Program")
    program = db.query_one("SELECT duration_years FROM program WHERE program_id = %s", (program_id,))
    if not program:
        raise ValueError("Select a valid program.")
    number = v.integer(form.get("semester_number"), "Semester number", 1, program["duration_years"] * 2)
    values = {
        "program_id": program_id,
        "semester_number": number,
        "academic_year_number": -(-number // 2),            # CEIL(number / 2)
    }
    if _count("SELECT COUNT(*) AS n FROM semester WHERE program_id = %s AND semester_number = %s AND semester_id <> %s",
              (program_id, number, record_id or -1)):
        raise ValueError("This program already has that semester number.")
    if record_id is not None:
        old = _existing("semester", "semester_id", record_id)
        if (old["program_id"], old["semester_number"]) != (program_id, number):
            linked = _count("""SELECT (SELECT COUNT(*) FROM student WHERE current_semester_id = %(s)s)
                                    + (SELECT COUNT(*) FROM course WHERE semester_id = %(s)s)
                                    + (SELECT COUNT(*) FROM course_registration WHERE semester_id = %(s)s)
                                    + (SELECT COUNT(*) FROM faculty_assignment WHERE semester_id = %(s)s) AS n""",
                            {"s": record_id})
            if linked:
                raise ValueError("This semester is used by students, courses or registrations, "
                                 "so its program and number cannot be changed.")
    return values


def clean_course(form, record_id):
    values = {
        "course_code": v.text(form.get("course_code"), "Course code", 30).upper(),
        "course_name": v.text(form.get("course_name"), "Course name", 150),
        "course_type": (form.get("course_type") or "").strip().upper(),
        "program_id": v.choice_id(form.get("program_id"), "Program"),
        "department_id": v.choice_id(form.get("department_id"), "Department"),
        "semester_id": v.choice_id(form.get("semester_id"), "Offered semester"),
    }
    if values["course_type"] not in ("CORE", "ELECTIVE"):
        raise ValueError("Course type must be CORE or ELECTIVE.")
    if not _same_program(values["department_id"], values["semester_id"], values["program_id"]):
        raise ValueError("The course's program, department and offered semester must all belong to the same program.")
    if _count("SELECT COUNT(*) AS n FROM course WHERE UPPER(course_code) = %s AND course_id <> %s",
              (values["course_code"], record_id or -1)):
        raise ValueError("Another course already uses this course code.")
    if record_id is None:
        # Optional initial official passing mark. Existing marks change only on the
        # Passing Mark Approvals page, so the change is always recorded.
        values["_initial_passing_mark"] = v.mark(form.get("passing_mark"), "Passing mark", required=False)
    else:
        old = _existing("course", "course_id", record_id)
        changed = any(old[k] != values[k] for k in ("course_type", "program_id", "department_id", "semester_id"))
        if changed and _count("SELECT COUNT(*) AS n FROM course_registration WHERE course_id = %s", (record_id,)):
            raise ValueError("Students have registered for this course, so its type, program, department and "
                             "offered semester cannot be changed.")
    return values


def after_create_course(new_id, values, admin_id):
    mark = values.get("_initial_passing_mark")
    if mark is not None:
        passing_marks.admin_set_passing_mark(new_id, mark, admin_id)


# ------------------------------------------------------------------ modules
MODULES = {
    "students": {
        "title": "Students", "singular": "Student", "table": "student", "pk": "student_id",
        "clean": clean_student,
        "fields": [
            {"name": "name", "label": "Student name", "type": "text", "required": True, "maxlength": 100},
            {"name": "email", "label": "Email", "type": "email", "required": True, "maxlength": 100},
            {"name": "password", "label": "Password", "type": "password",
             "help": "Required for a new student (min. 8 characters). When editing, leave blank to keep the current password."},
            {"name": "program_id", "label": "Program", "type": "select", "source": "programs", "required": True},
            {"name": "department_id", "label": "Department", "type": "select", "source": "departments", "required": True},
            {"name": "current_semester_id", "label": "Current semester", "type": "select", "source": "semesters", "required": True},
        ],
        "list_sql": """
            SELECT st.student_id, st.name, st.email, p.program_name, d.department_name,
                   'Semester ' || se.semester_number AS semester
            FROM student st
            JOIN program p ON p.program_id = st.program_id
            JOIN department d ON d.department_id = st.department_id
            JOIN semester se ON se.semester_id = st.current_semester_id
            ORDER BY st.student_id""",
        "columns": ["student_id", "name", "email", "program_name", "department_name", "semester"],
        "headers": ["ID", "Name", "Email", "Program", "Department", "Current semester"],
    },
    "faculty": {
        "title": "Faculty", "singular": "Faculty member", "table": "faculty", "pk": "faculty_id",
        "clean": clean_faculty,
        "fields": [
            {"name": "name", "label": "Faculty name", "type": "text", "required": True, "maxlength": 100},
            {"name": "email", "label": "Email", "type": "email", "required": True, "maxlength": 100},
            {"name": "password", "label": "Password", "type": "password",
             "help": "Required for a new account (min. 8 characters). When editing, leave blank to keep the current password."},
        ],
        "list_sql": "SELECT faculty_id, name, email FROM faculty ORDER BY faculty_id",
        "columns": ["faculty_id", "name", "email"],
        "headers": ["ID", "Name", "Email"],
    },
    "programs": {
        "title": "Programs", "singular": "Program", "table": "program", "pk": "program_id",
        "clean": clean_program,
        "fields": [
            {"name": "program_name", "label": "Program name", "type": "text", "required": True, "maxlength": 100},
            {"name": "program_type", "label": "Program type", "type": "text", "required": True, "maxlength": 50,
             "help": "Examples: B.Tech, PhD. Each program stands alone (PhD is not part of B.Tech)."},
            {"name": "duration_years", "label": "Duration (years)", "type": "number", "required": True, "min": 1, "max": 15},
        ],
        "list_sql": "SELECT program_id, program_name, program_type, duration_years FROM program ORDER BY program_id",
        "columns": ["program_id", "program_name", "program_type", "duration_years"],
        "headers": ["ID", "Program", "Type", "Duration (years)"],
    },
    "departments": {
        "title": "Departments", "singular": "Department", "table": "department", "pk": "department_id",
        "clean": clean_department,
        "fields": [
            {"name": "department_name", "label": "Department name", "type": "text", "required": True, "maxlength": 100},
            {"name": "program_id", "label": "Program", "type": "select", "source": "programs", "required": True},
        ],
        "list_sql": """
            SELECT d.department_id, d.department_name, p.program_name
            FROM department d JOIN program p ON p.program_id = d.program_id ORDER BY d.department_id""",
        "columns": ["department_id", "department_name", "program_name"],
        "headers": ["ID", "Department", "Program"],
    },
    "semesters": {
        "title": "Semesters", "singular": "Semester", "table": "semester", "pk": "semester_id",
        "clean": clean_semester,
        "fields": [
            {"name": "program_id", "label": "Program", "type": "select", "source": "programs", "required": True},
            {"name": "semester_number", "label": "Semester number", "type": "number", "required": True, "min": 1,
             "help": "The academic year is worked out automatically: semesters 1-2 are Year 1, 3-4 are Year 2, and so on."},
        ],
        "list_sql": """
            SELECT s.semester_id, p.program_name, s.semester_number, s.academic_year_number
            FROM semester s JOIN program p ON p.program_id = s.program_id
            ORDER BY s.program_id, s.semester_number""",
        "columns": ["semester_id", "program_name", "semester_number", "academic_year_number"],
        "headers": ["ID", "Program", "Semester", "Academic year"],
    },
    "courses": {
        "title": "Courses", "singular": "Course", "table": "course", "pk": "course_id",
        "clean": clean_course, "after_create": after_create_course,
        "fields": [
            {"name": "course_code", "label": "Course code", "type": "text", "required": True, "maxlength": 30},
            {"name": "course_name", "label": "Course name", "type": "text", "required": True, "maxlength": 150},
            {"name": "course_type", "label": "Course type", "type": "select_static",
             "options": ["CORE", "ELECTIVE"], "required": True},
            {"name": "program_id", "label": "Program", "type": "select", "source": "programs", "required": True},
            {"name": "department_id", "label": "Department", "type": "select", "source": "departments", "required": True},
            {"name": "semester_id", "label": "Offered semester", "type": "select", "source": "semesters", "required": True},
            {"name": "passing_mark", "label": "Passing mark (0-100)", "type": "number", "min": 0, "max": 100,
             "step": "0.01", "create_only": True,
             "help": "Optional. Leave blank if not decided yet. After the course exists, change it on the "
                     "Passing Mark Approvals page so the change is recorded."},
        ],
        "list_sql": """
            SELECT c.course_id, c.course_code, c.course_name, c.course_type, p.program_name,
                   d.department_name, 'Semester ' || s.semester_number AS semester, c.passing_mark
            FROM course c
            JOIN program p ON p.program_id = c.program_id
            JOIN department d ON d.department_id = c.department_id
            JOIN semester s ON s.semester_id = c.semester_id
            ORDER BY c.course_id""",
        "columns": ["course_id", "course_code", "course_name", "course_type", "program_name",
                    "department_name", "semester", "passing_mark"],
        "headers": ["ID", "Code", "Course", "Type", "Program", "Department", "Offered in", "Passing mark"],
    },
}

OPTION_QUERIES = {
    "programs": "SELECT program_id AS id, program_name AS label FROM program ORDER BY program_name",
    "departments": """SELECT d.department_id AS id, d.department_name || ' (' || p.program_name || ')' AS label
                      FROM department d JOIN program p ON p.program_id = d.program_id
                      ORDER BY p.program_name, d.department_name""",
    "semesters": """SELECT s.semester_id AS id, p.program_name || ' - Semester ' || s.semester_number AS label
                    FROM semester s JOIN program p ON p.program_id = s.program_id
                    ORDER BY p.program_name, s.semester_number""",
}
