"""Faculty assignment rules (admin) and the queries behind the faculty portal.

``faculty_assignment`` holds two row shapes (enforced by chk_faculty_assignment_type):
  * course-level : faculty, program, department, semester, course          (student/registration NULL)
  * student-level: the same plus student_id and the exact registration_id
For a student-level row, ``semester_id`` is the semester of that registration (so a reattempt
in a later semester is its own row) while program/department/course come from the course.
"""
import database as db
import registration_rules as rules


class AssignmentError(ValueError):
    """Safe-to-show message."""


def _faculty_ids(raw_ids):
    ids = []
    for raw in raw_ids:
        if not str(raw).strip().isdigit():
            raise AssignmentError("Select valid faculty members.")
        ids.append(int(raw))
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise AssignmentError("Select at least one faculty member.")
    return ids


def assign_course_level(program_id, department_id, academic_year, semester_id, course_id, raw_faculty_ids):
    """Assign one or more faculty to a course (caller commits). Returns ``(added, already)`` names."""
    faculty_ids = _faculty_ids(raw_faculty_ids)
    course = db.query_one("""
        SELECT c.course_id, c.program_id, c.department_id, c.semester_id, s.academic_year_number
        FROM course c JOIN semester s ON s.semester_id = c.semester_id
        WHERE c.course_id = %s FOR SHARE OF c""", (course_id,))
    if not course:
        raise AssignmentError("Select a valid course.")
    if course["program_id"] != program_id:
        raise AssignmentError("The selected course does not belong to the selected program.")
    if course["department_id"] != department_id:
        raise AssignmentError("The selected course does not belong to the selected department.")
    if course["semester_id"] != semester_id:
        raise AssignmentError("The selected course is not offered in the selected semester.")
    if course["academic_year_number"] != academic_year:
        raise AssignmentError("The selected semester does not belong to the selected academic year.")

    added, already = [], []
    for fid in faculty_ids:
        fac = db.query_one("SELECT faculty_id, name FROM faculty WHERE faculty_id = %s FOR SHARE", (fid,))
        if not fac:
            raise AssignmentError("A selected faculty member does not exist.")
        exists = db.query_one(
            "SELECT 1 AS ok FROM faculty_assignment WHERE faculty_id = %s AND course_id = %s AND student_id IS NULL",
            (fid, course_id))
        if exists:
            already.append(fac["name"])
            continue
        db.execute("""
            INSERT INTO faculty_assignment (assignment_id, faculty_id, program_id, department_id, semester_id, course_id)
            VALUES (%s, %s, %s, %s, %s, %s)""",
                   (db.next_id("faculty_assignment", "assignment_id"), fid, program_id, department_id,
                    semester_id, course_id))
        added.append(fac["name"])
    if not added:
        raise AssignmentError("Every selected faculty member is already assigned to this course.")
    return added, already


def assign_student_level(registration_id, raw_faculty_ids):
    """Assign faculty (already assigned to the course) to one exact registration (caller commits)."""
    faculty_ids = _faculty_ids(raw_faculty_ids)
    reg = db.query_one("""
        SELECT cr.registration_id, cr.student_id, cr.course_id, cr.semester_id, cr.registration_status,
               c.program_id, c.department_id
        FROM course_registration cr JOIN course c ON c.course_id = cr.course_id
        WHERE cr.registration_id = %s FOR SHARE OF cr""", (registration_id,))
    if not reg:
        raise AssignmentError("Select a valid registration.")
    if reg["registration_status"] == "CANCELLED":
        raise AssignmentError("This registration was cancelled and cannot be assigned.")

    added, already = [], []
    for fid in faculty_ids:
        fac = db.query_one("SELECT faculty_id, name FROM faculty WHERE faculty_id = %s", (fid,))
        if not fac:
            raise AssignmentError("A selected faculty member does not exist.")
        on_course = db.query_one("""
            SELECT 1 AS ok FROM faculty_assignment
            WHERE faculty_id = %s AND course_id = %s AND student_id IS NULL FOR SHARE""", (fid, reg["course_id"]))
        if not on_course:
            raise AssignmentError(f"{fac['name']} is not assigned to this course. Assign the faculty to the course first.")
        exists = db.query_one(
            "SELECT 1 AS ok FROM faculty_assignment WHERE faculty_id = %s AND registration_id = %s",
            (fid, registration_id))
        if exists:
            already.append(fac["name"])
            continue
        db.execute("""
            INSERT INTO faculty_assignment (assignment_id, faculty_id, program_id, department_id, semester_id,
                                            course_id, student_id, registration_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                   (db.next_id("faculty_assignment", "assignment_id"), fid, reg["program_id"],
                    reg["department_id"], reg["semester_id"], reg["course_id"], reg["student_id"], registration_id))
        added.append(fac["name"])
    if not added:
        raise AssignmentError("Every selected faculty member is already assigned to this registration.")
    return added, already


def remove_assignment(assignment_id):
    """Delete one assignment row (caller commits). A course-level row cannot go while
    student-level rows depend on it."""
    row = db.query_one("""SELECT assignment_id, faculty_id, course_id, student_id FROM faculty_assignment
                          WHERE assignment_id = %s FOR UPDATE""", (assignment_id,))
    if not row:
        raise AssignmentError("Assignment not found.")
    if row["student_id"] is None:
        dependants = db.query_one("""SELECT COUNT(*) AS n FROM faculty_assignment
                                     WHERE faculty_id = %s AND course_id = %s AND student_id IS NOT NULL""",
                                  (row["faculty_id"], row["course_id"]))["n"]
        if dependants:
            raise AssignmentError(
                f"This faculty member still has {dependants} student-level assignment(s) for this course. "
                "Remove those first.")
    db.execute("DELETE FROM faculty_assignment WHERE assignment_id = %s", (assignment_id,))
    return row


# ------------------------------------------------------------ admin lists
def course_level_list():
    return db.query_all("""
        SELECT fa.assignment_id, f.name AS faculty_name, f.email AS faculty_email, p.program_name,
               d.department_name, s.academic_year_number, s.semester_number, c.course_code, c.course_name
        FROM faculty_assignment fa
        JOIN faculty f ON f.faculty_id = fa.faculty_id JOIN program p ON p.program_id = fa.program_id
        JOIN department d ON d.department_id = fa.department_id JOIN semester s ON s.semester_id = fa.semester_id
        JOIN course c ON c.course_id = fa.course_id
        WHERE fa.student_id IS NULL
        ORDER BY p.program_name, s.semester_number, c.course_code, f.name""")


def student_level_list(student_id=None):
    where, params = ("AND fa.student_id = %s", (student_id,)) if student_id else ("", ())
    return db.query_all(f"""
        SELECT fa.assignment_id, fa.registration_id, f.name AS faculty_name, st.student_id, st.name AS student_name,
               c.course_code, c.course_name, s.semester_number, cr.result, cr.registration_status
        FROM faculty_assignment fa
        JOIN faculty f ON f.faculty_id = fa.faculty_id JOIN student st ON st.student_id = fa.student_id
        JOIN course c ON c.course_id = fa.course_id JOIN semester s ON s.semester_id = fa.semester_id
        JOIN course_registration cr ON cr.registration_id = fa.registration_id
        WHERE fa.student_id IS NOT NULL {where}
        ORDER BY st.name, c.course_code, s.semester_number, f.name""", params)


def course_faculty(course_id):
    """Faculty assigned at course level (the only ones a student-level assignment may use)."""
    return db.query_all("""
        SELECT f.faculty_id, f.name, f.email FROM faculty_assignment fa JOIN faculty f ON f.faculty_id = fa.faculty_id
        WHERE fa.course_id = %s AND fa.student_id IS NULL ORDER BY f.name""", (course_id,))


# --------------------------------------------------------- faculty portal
def faculty_courses(faculty_id):
    return db.query_all("""
        SELECT c.course_id, c.course_code, c.course_name, c.course_type, c.passing_mark,
               p.program_name, d.department_name, s.semester_number, s.academic_year_number,
               (SELECT COUNT(*) FROM faculty_assignment x
                  JOIN course_registration r ON r.registration_id = x.registration_id
                WHERE x.faculty_id = fa.faculty_id AND x.course_id = c.course_id
                  AND r.registration_status <> 'CANCELLED') AS student_count
        FROM faculty_assignment fa
        JOIN course c ON c.course_id = fa.course_id JOIN program p ON p.program_id = c.program_id
        JOIN department d ON d.department_id = c.department_id JOIN semester s ON s.semester_id = c.semester_id
        WHERE fa.faculty_id = %s AND fa.student_id IS NULL
        ORDER BY s.semester_number, c.course_code""", (faculty_id,))


def faculty_registrations(faculty_id):
    """Only registrations assigned to this faculty member (cancelled ones are hidden).

    ``attempt_rank`` is computed over ALL of the student's attempts of the course, so 'Current'
    always means the attempt that determines the student's result.
    """
    return db.query_all(f"""
        SELECT * FROM (
            SELECT cr.registration_id, st.student_id, st.name AS student_name, st.email AS student_email,
                   c.course_id, c.course_code, c.course_name, c.passing_mark AS official_passing_mark,
                   s.semester_number, cr.registration_date, cr.marks_obtained, cr.passing_mark_used,
                   cr.result, cr.registration_status, {rules.ATTEMPT_RANK_SQL} AS attempt_rank
            FROM course_registration cr
            JOIN student st ON st.student_id = cr.student_id JOIN course c ON c.course_id = cr.course_id
            JOIN semester s ON s.semester_id = cr.semester_id
        ) x
        WHERE registration_status <> 'CANCELLED'
          AND registration_id IN (SELECT registration_id FROM faculty_assignment
                                  WHERE faculty_id = %s AND registration_id IS NOT NULL)
        ORDER BY course_code, student_name, semester_number, registration_id""", (faculty_id,))
