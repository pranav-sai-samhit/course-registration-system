"""Admin: faculty assignment (course-level and student-level) and marks management."""
import psycopg2
from flask import current_app, flash, redirect, render_template, request, url_for

import assignments
import database as db
import marks as marks_logic
import passing_marks
import navigation
import security
import validators as v

admin_only = security.role_required("admin")


def _item():
    return navigation.find("admin", "faculty_assignments")


def _db_failure(action):
    db.rollback()
    current_app.logger.exception("%s failed", action)
    flash("The change could not be saved. Please check the selections and try again.", "error")


def register(bp):
    # ------------------------------------------------------------ landing
    @bp.route("/faculty-assignments", endpoint="faculty_assignments")
    @admin_only
    def landing():
        return render_template("admin_assign_home.html", role="admin", item=_item())

    # -------------------------------------------------------- course level
    def course_page(values=None, status=200):
        programs = db.query_all("SELECT program_id, program_name FROM program ORDER BY program_name")
        departments = db.query_all("SELECT department_id, department_name, program_id FROM department "
                                   "ORDER BY department_name")
        semesters = db.query_all("SELECT semester_id, program_id, semester_number, academic_year_number "
                                 "FROM semester ORDER BY program_id, semester_number")
        years = sorted({(s["program_id"], s["academic_year_number"]) for s in semesters})
        courses = db.query_all("SELECT course_id, course_code, course_name, program_id, department_id, semester_id "
                               "FROM course ORDER BY course_code")
        faculty = db.query_all("SELECT faculty_id, name, email FROM faculty ORDER BY name")
        return render_template(
            "admin_assign_course.html", role="admin", item=_item(), programs=programs, departments=departments,
            semesters=semesters, years=years, courses=courses, faculty=faculty,
            assignments=assignments.course_level_list(), values=values or {},
            selected_faculty=set((values or {}).get("faculty_ids", []))), status

    @bp.route("/faculty-assignments/course-level", methods=["GET", "POST"], endpoint="faculty_assignments_course")
    @admin_only
    def course_level():
        if request.method == "GET":
            return course_page()
        form = request.form
        try:
            added, already = assignments.assign_course_level(
                v.choice_id(form.get("program_id"), "Program"),
                v.choice_id(form.get("department_id"), "Department"),
                v.integer(form.get("academic_year"), "Academic year", minimum=1),
                v.choice_id(form.get("semester_id"), "Semester"),
                v.choice_id(form.get("course_id"), "Course"),
                form.getlist("faculty_ids"))
            db.commit()
            msg = "Assigned: " + ", ".join(added) + "."
            if already:
                msg += " Already assigned (unchanged): " + ", ".join(already) + "."
            flash(msg, "success")
            return redirect(url_for("admin.faculty_assignments_course"))
        except ValueError as exc:                 # includes AssignmentError
            db.rollback()
            flash(str(exc), "error")
        except psycopg2.Error:
            _db_failure("Course-level assignment")
        values = form.to_dict()
        values["faculty_ids"] = form.getlist("faculty_ids")
        return course_page(values, 400)

    # ------------------------------------------------------- student level
    def student_page(status=200):
        student_id = request.args.get("student_id", "").strip()
        registration_id = request.args.get("registration_id", "").strip()
        students = db.query_all("""
            SELECT st.student_id, st.name, p.program_name, d.department_name
            FROM student st JOIN program p ON p.program_id = st.program_id
            JOIN department d ON d.department_id = st.department_id ORDER BY st.name""")
        student = registrations = reg = faculty = assigned_ids = None
        if student_id.isdigit():
            student = db.query_one("SELECT student_id, name FROM student WHERE student_id = %s", (int(student_id),))
        if student:
            registrations = db.query_all("""
                SELECT cr.registration_id, c.course_code, c.course_name, s.semester_number, cr.result,
                       cr.registration_status,
                       (SELECT COUNT(*) FROM faculty_assignment fa WHERE fa.registration_id = cr.registration_id) AS assigned
                FROM course_registration cr JOIN course c ON c.course_id = cr.course_id
                JOIN semester s ON s.semester_id = cr.semester_id
                WHERE cr.student_id = %s AND cr.registration_status <> 'CANCELLED'
                ORDER BY c.course_code, s.semester_number, cr.registration_id""", (student["student_id"],))
            if registration_id.isdigit():
                reg = next((r for r in registrations if r["registration_id"] == int(registration_id)), None)
            if reg:
                course_id = db.query_one("SELECT course_id FROM course_registration WHERE registration_id = %s",
                                         (reg["registration_id"],))["course_id"]
                faculty = assignments.course_faculty(course_id)
                assigned_ids = {r["faculty_id"] for r in db.query_all(
                    "SELECT faculty_id FROM faculty_assignment WHERE registration_id = %s", (reg["registration_id"],))}
        return render_template(
            "admin_assign_student.html", role="admin", item=_item(), students=students, student=student,
            registrations=registrations, reg=reg, faculty=faculty, assigned_ids=assigned_ids or set(),
            assignments=assignments.student_level_list(student["student_id"] if student else None)), status

    @bp.route("/faculty-assignments/student-level", endpoint="faculty_assignments_student")
    @admin_only
    def student_level():
        return student_page()

    @bp.route("/faculty-assignments/student-level/save", methods=["POST"], endpoint="faculty_assignments_student_save")
    @admin_only
    def student_level_save():
        registration_id = None
        try:
            registration_id = v.choice_id(request.form.get("registration_id"), "Registration")
            added, already = assignments.assign_student_level(registration_id, request.form.getlist("faculty_ids"))
            db.commit()
            msg = "Assigned: " + ", ".join(added) + "."
            if already:
                msg += " Already assigned (unchanged): " + ", ".join(already) + "."
            flash(msg, "success")
        except ValueError as exc:
            db.rollback()
            flash(str(exc), "error")
        except psycopg2.Error:
            _db_failure("Student-level assignment")
        student_id = request.form.get("student_id", "")
        return redirect(url_for("admin.faculty_assignments_student", student_id=student_id,
                                registration_id=registration_id or ""))

    # ------------------------------------------------------------- remove
    @bp.route("/faculty-assignments/<int:assignment_id>/remove", methods=["POST"], endpoint="faculty_assignment_remove")
    @admin_only
    def remove(assignment_id):
        back = "faculty_assignments_student" if request.form.get("level") == "student" else "faculty_assignments_course"
        try:
            assignments.remove_assignment(assignment_id)
            db.commit()
            flash("Assignment removed.", "success")
        except ValueError as exc:
            db.rollback()
            flash(str(exc), "error")
        except psycopg2.Error:
            _db_failure("Remove assignment")
        kwargs = {}
        if back == "faculty_assignments_student" and request.form.get("student_id", "").isdigit():
            kwargs["student_id"] = request.form["student_id"]
        return redirect(url_for(f"admin.{back}", **kwargs))

    # ------------------------------------------------------- admin marks
    @bp.route("/registrations/<int:registration_id>/marks", methods=["GET", "POST"], endpoint="registration_marks")
    @admin_only
    def registration_marks(registration_id):
        reg = db.query_one("""
            SELECT cr.registration_id, st.name AS student_name, c.course_code, c.course_name, c.passing_mark,
                   s.semester_number, cr.marks_obtained, cr.passing_mark_used, cr.result, cr.registration_status
            FROM course_registration cr JOIN student st ON st.student_id = cr.student_id
            JOIN course c ON c.course_id = cr.course_id JOIN semester s ON s.semester_id = cr.semester_id
            WHERE cr.registration_id = %s""", (registration_id,))
        if not reg:
            flash("Registration not found.", "error")
            return redirect(url_for("admin.registrations"))
        status = 200
        if request.method == "POST":
            try:
                value = v.mark(request.form.get("marks"), "Marks")
                result, used = marks_logic.save_marks(registration_id, value)
                db.commit()
                flash(f"Marks saved: {result} (passing mark applied: {used}).", "success")
                return redirect(url_for("admin.registrations"))
            except ValueError as exc:             # includes MarksError / MissingPassingMark
                db.rollback()
                flash(str(exc), "error")
                status = 400
            except psycopg2.Error:
                _db_failure("Admin marks entry")
                status = 400
        return render_template("admin_marks.html", role="admin", item=navigation.find("admin", "registrations"),
                               reg=reg, posted=request.form.get("marks", "")), status

    # ---------------------------------------------- passing mark approvals
    def approvals_page(status=200, values=None):
        rows_ = passing_marks.history()
        courses = db.query_all("""SELECT course_id, course_code, course_name, passing_mark FROM course
                                  ORDER BY course_code""")
        return render_template("admin_approvals.html", role="admin",
                               item=navigation.find("admin", "passing_mark_approvals"),
                               pending=[r for r in rows_ if r["admin_status"] == "PENDING"],
                               history=[r for r in rows_ if r["admin_status"] != "PENDING"],
                               courses=courses, values=values or {}), status

    @bp.route("/passing-mark-approvals", endpoint="passing_mark_approvals")
    @admin_only
    def approvals():
        return approvals_page()

    @bp.route("/passing-mark-approvals/<int:approval_id>/<action>", methods=["POST"], endpoint="approval_decide")
    @admin_only
    def decide(approval_id, action):
        try:
            if action not in ("approve", "reject"):
                raise ValueError("Unknown action.")
            passing_marks.admin_decide(approval_id, security.current_user_id(), action == "approve")
            db.commit()
            flash("Proposal approved; the official passing mark was updated." if action == "approve"
                  else "Proposal rejected; the official passing mark is unchanged.", "success")
        except ValueError as exc:
            db.rollback()
            flash(str(exc), "error")
        except psycopg2.Error:
            _db_failure("Approval decision")
        return redirect(url_for("admin.passing_mark_approvals"))

    @bp.route("/passing-mark-approvals/set", methods=["POST"], endpoint="passing_mark_set")
    @admin_only
    def set_mark():
        try:
            course_id = v.choice_id(request.form.get("course_id"), "Course")
            value = v.mark(request.form.get("passing_mark"), "Passing mark")
            current = db.query_one("SELECT passing_mark FROM course WHERE course_id = %s FOR UPDATE", (course_id,))
            if not current:
                raise ValueError("Select a valid course.")
            if current["passing_mark"] is not None and current["passing_mark"] == value:
                raise ValueError("That is already the official passing mark for this course.")
            passing_marks.admin_set_passing_mark(course_id, value, security.current_user_id())
            db.commit()
            flash("Official passing mark updated and recorded in the approval history.", "success")
            return redirect(url_for("admin.passing_mark_approvals"))
        except ValueError as exc:
            db.rollback()
            flash(str(exc), "error")
        except psycopg2.Error:
            _db_failure("Direct passing-mark change")
        return approvals_page(400, request.form.to_dict())
