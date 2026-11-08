"""Course-registration business rules, shared by the admin and student portals.

Rules enforced by ``check_registration``:
  * student, course and semester must exist; semester must belong to the student's program
  * the course must belong to the student's program and department
  * the semester cannot be later than the student's current semester (past semesters are
    allowed so an admin can record history; self-service is limited to the current one)
  * one row per (student, course, semester) - duplicates are refused
  * a course already PASSED can never be registered again
  * a FAILED course can be reattempted only in a LATER semester than the latest attempt;
    every reattempt is a new row, so earlier attempts, marks and results are preserved
  * an attempt still awaiting a result blocks a further attempt
  * a first-time registration is only possible in the semester the course is offered
  * at most TWO elective courses per student per semester
No passing mark is required to register.
"""
import database as db

MAX_ELECTIVES = 2

# SQL fragment: 1 = latest non-cancelled attempt of that student+course, 2.. = older,
# NULL = cancelled. Use inside a SELECT that also joins `semester s` as the registration's semester.
ATTEMPT_RANK_SQL = """
    CASE WHEN cr.registration_status = 'CANCELLED' THEN NULL ELSE
        ROW_NUMBER() OVER (
            PARTITION BY cr.student_id, cr.course_id,
                         (cr.registration_status = 'CANCELLED')
            ORDER BY s.semester_number DESC, cr.registration_date DESC, cr.registration_id DESC)
    END
"""


class RegistrationError(ValueError):
    """A rule was broken; the message is safe to show to the user."""


def check_registration(student_id, course_id, semester_id,
                       exclude_registration_id=None, require_current_semester=False):
    """Validate a registration. Returns ``(student, course, semester)`` rows or raises."""
    # Lock the student row so two simultaneous requests cannot both slip past the elective limit.
    student = db.query_one("""
        SELECT st.student_id, st.program_id, st.department_id, st.current_semester_id,
               cur.semester_number AS current_semester_number
        FROM student st JOIN semester cur ON cur.semester_id = st.current_semester_id
        WHERE st.student_id = %s FOR UPDATE OF st
    """, (student_id,))
    if not student:
        raise RegistrationError("Select a valid student.")

    course = db.query_one("""
        SELECT course_id, course_code, course_name, course_type, program_id, department_id, semester_id
        FROM course WHERE course_id = %s""", (course_id,))
    if not course:
        raise RegistrationError("Select a valid course.")

    semester = db.query_one(
        "SELECT semester_id, program_id, semester_number FROM semester WHERE semester_id = %s", (semester_id,))
    if not semester:
        raise RegistrationError("Select a valid semester.")

    if semester["program_id"] != student["program_id"]:
        raise RegistrationError("The semester does not belong to the student's program.")
    if course["program_id"] != student["program_id"]:
        raise RegistrationError("The course does not belong to the student's program.")
    if course["department_id"] != student["department_id"]:
        raise RegistrationError("The course does not belong to the student's department.")
    if semester["semester_number"] > student["current_semester_number"]:
        raise RegistrationError(
            f"The student has not reached semester {semester['semester_number']} yet "
            f"(current semester is {student['current_semester_number']}).")
    if require_current_semester and semester_id != student["current_semester_id"]:
        raise RegistrationError("You can register only in your current semester.")

    exclude = exclude_registration_id if exclude_registration_id is not None else -1

    previous = db.query_all("""
        SELECT cr.result, s.semester_number
        FROM course_registration cr JOIN semester s ON s.semester_id = cr.semester_id
        WHERE cr.student_id = %s AND cr.course_id = %s
          AND cr.registration_status <> 'CANCELLED' AND cr.registration_id <> %s
        ORDER BY s.semester_number DESC, cr.registration_date DESC, cr.registration_id DESC
    """, (student_id, course_id, exclude))
    if any(p["result"] == "PASS" for p in previous):
        raise RegistrationError("The student has already passed this course and cannot register for it again.")

    duplicate = db.query_one("""
        SELECT registration_status FROM course_registration
        WHERE student_id = %s AND course_id = %s AND semester_id = %s AND registration_id <> %s
    """, (student_id, course_id, semester_id, exclude))
    if duplicate:
        if duplicate["registration_status"] == "CANCELLED":
            raise RegistrationError(
                "A cancelled registration already exists for this course and semester. "
                "Restore that registration instead of creating a new one.")
        raise RegistrationError("The student is already registered for this course in this semester.")

    if previous:
        latest = previous[0]
        if latest["result"] != "FAIL":
            raise RegistrationError(
                "The previous attempt has no result yet. A course can be reattempted only after it is marked FAIL.")
        if semester["semester_number"] <= latest["semester_number"]:
            raise RegistrationError(
                "A failed course can be reattempted only in a later semester than the previous attempt.")
    elif semester_id != course["semester_id"]:
        raise RegistrationError("A course can be registered for the first time only in the semester it is offered.")

    if course["course_type"] == "ELECTIVE":
        count = db.query_one("""
            SELECT COUNT(*) AS n FROM course_registration cr
            JOIN course c ON c.course_id = cr.course_id
            WHERE cr.student_id = %s AND cr.semester_id = %s AND c.course_type = 'ELECTIVE'
              AND cr.registration_status <> 'CANCELLED' AND cr.registration_id <> %s
        """, (student_id, semester_id, exclude))["n"]
        if count >= MAX_ELECTIVES:
            raise RegistrationError(
                f"A student can take at most {MAX_ELECTIVES} elective courses in one semester.")

    return student, course, semester


def create_registration(student_id, course_id, semester_id, require_current_semester=False):
    """Validate and insert a registration (caller commits). Returns the new registration_id.

    passing_mark_used is left NULL: it is recorded when marks are saved (the official
    passing mark at that moment), so a missing passing mark never blocks registration.
    """
    check_registration(student_id, course_id, semester_id,
                       require_current_semester=require_current_semester)
    registration_id = db.next_id("course_registration", "registration_id")
    db.execute("""
        INSERT INTO course_registration (registration_id, student_id, course_id, semester_id)
        VALUES (%s, %s, %s, %s)
    """, (registration_id, student_id, course_id, semester_id))
    return registration_id


# ------------------------------------------------------------- student views
def student_attempts(student_id):
    """Every registration row of one student, newest attempt of each course first.

    ``attempt_rank`` is 1 for the latest non-cancelled attempt (the one that determines the
    current result), 2.. for older ones, and None for cancelled rows. ``attempt_number`` counts
    non-cancelled attempts of the course from the oldest (1) upward.
    """
    return db.query_all(f"""
        SELECT * FROM (
            SELECT cr.registration_id, cr.course_id, c.course_code, c.course_name, c.course_type,
                   s.semester_number, CEIL(s.semester_number / 2.0)::int AS academic_year,
                   cr.registration_date, cr.marks_obtained, cr.passing_mark_used, cr.result,
                   cr.registration_status, {ATTEMPT_RANK_SQL} AS attempt_rank,
                   CASE WHEN cr.registration_status = 'CANCELLED' THEN NULL ELSE
                        ROW_NUMBER() OVER (
                            PARTITION BY cr.student_id, cr.course_id, (cr.registration_status = 'CANCELLED')
                            ORDER BY s.semester_number, cr.registration_date, cr.registration_id)
                   END AS attempt_number
            FROM course_registration cr
            JOIN course c   ON c.course_id = cr.course_id
            JOIN semester s ON s.semester_id = cr.semester_id
            WHERE cr.student_id = %s
        ) x
        ORDER BY course_code, semester_number DESC, registration_id DESC
    """, (student_id,))


def course_options(student_id):
    """What a student can do with each course of their own program and department.

    Returns ``(student, options, elective_count)``. Each option has ``kind``:
      NEW        - first attempt, offered in the student's current semester
      REATTEMPT  - latest attempt failed in an earlier semester
    and ``blocked`` (a reason string, or None) when the course is listed but cannot be taken now.
    Passed courses and courses with an attempt still awaiting a result are not offered.
    The rules themselves are enforced again by ``check_registration`` when registering.
    """
    student = db.query_one("""
        SELECT st.student_id, st.program_id, st.department_id, st.current_semester_id,
               cur.semester_number AS current_semester_number
        FROM student st JOIN semester cur ON cur.semester_id = st.current_semester_id
        WHERE st.student_id = %s""", (student_id,))
    if not student:
        return None, [], 0
    courses = db.query_all("""
        SELECT c.course_id, c.course_code, c.course_name, c.course_type, c.semester_id,
               s.semester_number AS offered_semester_number, c.passing_mark
        FROM course c JOIN semester s ON s.semester_id = c.semester_id
        WHERE c.program_id = %s AND c.department_id = %s
        ORDER BY c.course_code""", (student["program_id"], student["department_id"]))
    regs = db.query_all("""
        SELECT cr.course_id, cr.semester_id, cr.result, cr.registration_status, s.semester_number
        FROM course_registration cr JOIN semester s ON s.semester_id = cr.semester_id
        WHERE cr.student_id = %s
        ORDER BY s.semester_number DESC, cr.registration_date DESC, cr.registration_id DESC
    """, (student_id,))
    by_course = {}
    for r in regs:
        by_course.setdefault(r["course_id"], []).append(r)

    current_sem = student["current_semester_number"]
    elective_count = sum(
        1 for c in courses for r in by_course.get(c["course_id"], [])
        if c["course_type"] == "ELECTIVE" and r["semester_id"] == student["current_semester_id"]
        and r["registration_status"] != "CANCELLED")

    options = []
    for c in courses:
        mine = by_course.get(c["course_id"], [])
        active = [r for r in mine if r["registration_status"] != "CANCELLED"]
        if any(r["result"] == "PASS" for r in active):
            continue
        if active:
            latest = active[0]
            if latest["result"] != "FAIL" or current_sem <= latest["semester_number"]:
                continue                       # in progress, or failed in this very semester
            kind = "REATTEMPT"
        elif c["semester_id"] == student["current_semester_id"]:
            kind = "NEW"
        else:
            continue
        blocked = None
        if any(r["semester_id"] == student["current_semester_id"] and r["registration_status"] == "CANCELLED"
               for r in mine):
            blocked = "A cancelled registration exists for this semester. Ask the administrator to restore it."
        elif c["course_type"] == "ELECTIVE" and elective_count >= MAX_ELECTIVES:
            blocked = f"Elective limit reached ({MAX_ELECTIVES} per semester)."
        options.append(dict(c, kind=kind, blocked=blocked))
    return student, options, elective_count
