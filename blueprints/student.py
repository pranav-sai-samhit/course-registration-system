"""Student portal."""
import psycopg2
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

import database as db
import navigation
import registration_rules as rules
import security
import validators as v
from blueprints._common import dashboard_view

bp = Blueprint("student", __name__, url_prefix="/student")
bp.add_url_rule("/dashboard", endpoint="dashboard", view_func=dashboard_view("student"))


@bp.route("/profile")
@security.role_required("student")
def profile():
    # Always the signed-in student's own row - the ID comes from the session, never the URL.
    student = db.query_one("""
        SELECT st.student_id, st.name, st.email,
               p.program_name, p.program_type, d.department_name,
               se.semester_number, CEIL(se.semester_number / 2.0)::int AS academic_year
        FROM student st
        JOIN program p     ON p.program_id = st.program_id
        JOIN department d  ON d.department_id = st.department_id
        JOIN semester se   ON se.semester_id = st.current_semester_id
        WHERE st.student_id = %s
    """, (security.current_user_id(),))
    return render_template("student_profile.html", role="student",
                           item=navigation.find("student", "profile"), student=student)


def _page(template, key, **context):
    return render_template(template, role="student", item=navigation.find("student", key), **context)


@bp.route("/available-courses")
@security.role_required("student")
def available_courses():
    student, options, elective_count = rules.course_options(security.current_user_id())
    if not student:
        flash("Your student record could not be found. Contact the administrator.", "error")
        return redirect(url_for("student.dashboard"))
    return _page("student_available.html", "available_courses", options=options,
                 elective_count=elective_count, max_electives=rules.MAX_ELECTIVES,
                 semester_number=student["current_semester_number"])


@bp.route("/available-courses/register", methods=["POST"], endpoint="register_course")
@security.role_required("student")
def register_course():
    """Self-registration. Student and semester come from the session/database, never the form."""
    student_id = security.current_user_id()
    try:
        course_id = v.choice_id(request.form.get("course_id"), "Course")
        row = db.query_one("SELECT current_semester_id FROM student WHERE student_id = %s", (student_id,))
        if not row:
            raise ValueError("Your student record could not be found.")
        rules.create_registration(student_id, course_id, row["current_semester_id"],
                                  require_current_semester=True)
        db.commit()
        flash("You are now registered for the course.", "success")
    except ValueError as exc:                       # includes RegistrationError
        db.rollback()
        flash(str(exc), "error")
    except psycopg2.Error:
        db.rollback()
        current_app.logger.exception("Student registration failed")
        flash("Could not complete the registration. Please try again.", "error")
    return redirect(url_for("student.available_courses"))


@bp.route("/registrations")
@security.role_required("student")
def my_registrations():
    return _page("student_registrations.html", "my_registrations",
                 attempts=rules.student_attempts(security.current_user_id()))


@bp.route("/marks")
@security.role_required("student")
def my_marks():
    attempts = [a for a in rules.student_attempts(security.current_user_id())
                if a["registration_status"] != "CANCELLED"]
    return _page("student_marks.html", "my_marks", attempts=attempts)


@bp.route("/results")
@security.role_required("student")
def my_results():
    attempts = rules.student_attempts(security.current_user_id())
    live = [a for a in attempts if a["registration_status"] != "CANCELLED"]
    current = [a for a in live if a["attempt_rank"] == 1]            # latest attempt decides
    history = [a for a in live if a["attempt_rank"] != 1]
    student, options, _ = rules.course_options(security.current_user_id())
    eligible = [o for o in options if o["kind"] == "REATTEMPT"]
    waiting = [a for a in current if a["result"] == "FAIL" and a["course_id"] not in
               {o["course_id"] for o in eligible}]
    return _page("student_results.html", "my_results", current=current, history=history,
                 eligible=eligible, waiting=waiting)
