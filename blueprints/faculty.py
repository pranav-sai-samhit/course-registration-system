"""Faculty portal. Everything is scoped to the signed-in faculty member (ID from the session)."""
import psycopg2
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

import assignments
import database as db
import marks as marks_logic
import passing_marks
import navigation
import security
import validators as v
from blueprints._common import dashboard_view, register_placeholders

bp = Blueprint("faculty", __name__, url_prefix="/faculty")
bp.add_url_rule("/dashboard", endpoint="dashboard", view_func=dashboard_view("faculty"))


def _page(template, key, **context):
    return render_template(template, role="faculty", item=navigation.find("faculty", key), **context)


@bp.route("/courses", endpoint="my_courses")
@security.role_required("faculty")
def my_courses():
    return _page("faculty_courses.html", "my_courses", courses=assignments.faculty_courses(security.current_user_id()))


@bp.route("/students", endpoint="my_students")
@security.role_required("faculty")
def my_students():
    return _page("faculty_students.html", "my_students",
                 registrations=assignments.faculty_registrations(security.current_user_id()))


@bp.route("/marks", endpoint="marks_entry")
@security.role_required("faculty")
def marks_entry():
    regs = assignments.faculty_registrations(security.current_user_id())
    pending = [r for r in regs if r["result"] == "PENDING"]
    graded = [r for r in regs if r["result"] != "PENDING"]
    return _page("faculty_marks.html", "marks_entry", pending=pending, graded=graded,
                 no_mark_message=marks_logic.NO_PASSING_MARK_MESSAGE)


@bp.route("/marks/save", methods=["POST"], endpoint="save_marks")
@security.role_required("faculty")
def save_marks():
    try:
        registration_id = v.choice_id(request.form.get("registration_id"), "Registration")
        value = v.mark(request.form.get("marks"), "Marks")
        result, used = marks_logic.save_marks(registration_id, value, faculty_id=security.current_user_id())
        db.commit()
        flash(f"Marks saved. Result: {result} (passing mark applied: {used}).", "success")
    except ValueError as exc:                    # MarksError, MissingPassingMark, validation
        db.rollback()
        flash(str(exc), "error")
    except psycopg2.Error:
        db.rollback()
        current_app.logger.exception("Marks entry failed")
        flash("The marks could not be saved. Please try again.", "error")
    return redirect(url_for("faculty.marks_entry"))


@bp.route("/results", endpoint="student_results")
@security.role_required("faculty")
def student_results():
    regs = assignments.faculty_registrations(security.current_user_id())
    return _page("faculty_results.html", "student_results", registrations=regs)


def _requests_page(status=200, values=None):
    fid = security.current_user_id()
    return _page("faculty_requests.html", "passing_mark_requests", courses=assignments.faculty_courses(fid),
                 proposals=passing_marks.history(fid), values=values or {}), status


@bp.route("/passing-mark-requests", endpoint="passing_mark_requests")
@security.role_required("faculty")
def passing_mark_requests():
    return _requests_page()


@bp.route("/passing-mark-requests/propose", methods=["POST"], endpoint="propose_mark")
@security.role_required("faculty")
def propose_mark():
    try:
        passing_marks.faculty_propose(security.current_user_id(),
                                      v.choice_id(request.form.get("course_id"), "Course"),
                                      v.mark(request.form.get("passing_mark"), "Passing mark"))
        db.commit()
        flash("Proposal submitted. The administrator will review it.", "success")
        return redirect(url_for("faculty.passing_mark_requests"))
    except ValueError as exc:
        db.rollback()
        flash(str(exc), "error")
    except psycopg2.Error:
        db.rollback()
        current_app.logger.exception("Proposal failed")
        flash("The proposal could not be saved. Please try again.", "error")
    return _requests_page(400, request.form.to_dict())


@bp.route("/passing-mark-requests/<int:approval_id>/edit", methods=["POST"], endpoint="edit_proposal")
@security.role_required("faculty")
def edit_proposal(approval_id):
    try:
        passing_marks.faculty_edit(security.current_user_id(), approval_id,
                                   v.mark(request.form.get("passing_mark"), "Passing mark"))
        db.commit()
        flash("Your pending proposal was updated.", "success")
    except ValueError as exc:
        db.rollback()
        flash(str(exc), "error")
    except psycopg2.Error:
        db.rollback()
        current_app.logger.exception("Proposal edit failed")
        flash("The proposal could not be updated. Please try again.", "error")
    return redirect(url_for("faculty.passing_mark_requests"))


register_placeholders(bp, "faculty")
