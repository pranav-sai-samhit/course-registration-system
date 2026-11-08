"""Administrator portal: academic-management modules and registrations."""
import psycopg2
from psycopg2 import errors
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

import database as db
import navigation
import registration_rules as rules
import security
import validators as v
from blueprints._common import dashboard_view, register_placeholders
from blueprints.admin_modules import MODULES, OPTION_QUERIES

bp = Blueprint("admin", __name__, url_prefix="/admin")
bp.add_url_rule("/dashboard", endpoint="dashboard", view_func=dashboard_view("admin"))

admin_only = security.role_required("admin")

DB_ERROR_MESSAGES = (
    (errors.UniqueViolation, "A record with these values already exists."),
    (errors.ForeignKeyViolation, "A selected or linked record does not exist or is still in use."),
    (errors.CheckViolation, "The values break a database rule. Check the numbers and selections."),
)


def _db_message(exc, default):
    for kind, message in DB_ERROR_MESSAGES:
        if isinstance(exc, kind):
            return message
    return default


# ===================================================================== CRUD
def _choices(field):
    if field["type"] == "select":
        return [(r["id"], r["label"]) for r in db.query_all(OPTION_QUERIES[field["source"]])]
    if field["type"] == "select_static":
        return [(o, o) for o in field["options"]]
    return None


def _render_module(key, edit_id=None, values=None, status=200):
    cfg = MODULES[key]
    edit_record = None
    if edit_id is not None:
        edit_record = db.query_one(f"SELECT * FROM {cfg['table']} WHERE {cfg['pk']} = %s", (edit_id,))
        if not edit_record:
            flash("Record not found.", "error")
            return redirect(url_for(f"admin.{key}"))
    if values is None and edit_record:
        values = {k: ("" if val is None else str(val)) for k, val in edit_record.items()
                  if not k.startswith("password")}
    fields = [dict(f, choices=_choices(f)) for f in cfg["fields"]]
    return render_template(
        "admin_module.html", role="admin", item=navigation.find("admin", key), cfg=cfg, key=key,
        fields=fields, records=db.query_all(cfg["list_sql"]), edit_id=edit_id, values=values or {},
    ), status


def _save(key, record_id=None):
    """Validate the posted form and insert/update. Returns the saved id."""
    cfg = MODULES[key]
    values = cfg["clean"](request.form, record_id)
    columns = {k: val for k, val in values.items() if not k.startswith("_")}
    if record_id is None:
        record_id = db.next_id(cfg["table"], cfg["pk"])
        names = [cfg["pk"], *columns]
        db.execute(f"INSERT INTO {cfg['table']} ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))})",
                   [record_id, *columns.values()])
        if "after_create" in cfg:
            cfg["after_create"](record_id, values, security.current_user_id())
    else:
        assignments = ", ".join(f"{name} = %s" for name in columns)
        if db.execute(f"UPDATE {cfg['table']} SET {assignments} WHERE {cfg['pk']} = %s",
                      [*columns.values(), record_id]) == 0:
            raise ValueError("Record not found.")
    return record_id


def _make_list_view(key):
    @admin_only
    def list_view():
        cfg = MODULES[key]
        if request.method == "POST":
            try:
                _save(key)
                db.commit()
                flash(f"{cfg['singular']} added successfully.", "success")
                return redirect(url_for(f"admin.{key}"))
            except ValueError as exc:
                db.rollback()
                flash(str(exc), "error")
            except psycopg2.Error as exc:
                db.rollback()
                current_app.logger.exception("Create %s failed", key)
                flash(_db_message(exc, "Could not save the record."), "error")
            return _render_module(key, values=request.form.to_dict(), status=400)
        return _render_module(key)
    list_view.__name__ = key
    return list_view


def _make_edit_view(key):
    @admin_only
    def edit_view(record_id):
        cfg = MODULES[key]
        if request.method == "POST":
            try:
                _save(key, record_id)
                db.commit()
                flash(f"{cfg['singular']} updated successfully.", "success")
                return redirect(url_for(f"admin.{key}"))
            except ValueError as exc:
                db.rollback()
                flash(str(exc), "error")
            except psycopg2.Error as exc:
                db.rollback()
                current_app.logger.exception("Update %s failed", key)
                flash(_db_message(exc, "Could not update the record."), "error")
            return _render_module(key, edit_id=record_id, values=request.form.to_dict(), status=400)
        return _render_module(key, edit_id=record_id)
    edit_view.__name__ = f"{key}_edit"
    return edit_view


def _make_delete_view(key):
    @admin_only
    def delete_view(record_id):
        cfg = MODULES[key]
        try:
            if db.execute(f"DELETE FROM {cfg['table']} WHERE {cfg['pk']} = %s", (record_id,)):
                db.commit()
                flash(f"{cfg['singular']} deleted.", "success")
            else:
                db.rollback()
                flash("Record not found.", "error")
        except errors.ForeignKeyViolation:
            db.rollback()
            flash(f"This {cfg['singular'].lower()} is linked to other records (registrations, assignments, "
                  "courses, etc.) and cannot be deleted. Remove or reassign those links first.", "error")
        except psycopg2.Error:
            db.rollback()
            current_app.logger.exception("Delete %s failed", key)
            flash("Could not delete the record.", "error")
        return redirect(url_for(f"admin.{key}"))
    delete_view.__name__ = f"{key}_delete"
    return delete_view


for _key, _cfg in MODULES.items():
    _path = navigation.find("admin", _key)["path"]
    bp.add_url_rule(_path, endpoint=_key, view_func=_make_list_view(_key), methods=["GET", "POST"])
    bp.add_url_rule(f"{_path}/<int:record_id>/edit", endpoint=f"{_key}_edit",
                    view_func=_make_edit_view(_key), methods=["GET", "POST"])
    bp.add_url_rule(f"{_path}/<int:record_id>/delete", endpoint=f"{_key}_delete",
                    view_func=_make_delete_view(_key), methods=["POST"])


# ============================================================= registrations
def _registration_page(values=None, status=200):
    student_filter = request.args.get("student_id", "").strip()
    status_filter = request.args.get("status", "").strip().upper()
    where, params = [], []
    if student_filter.isdigit():
        where.append("student_id = %s")
        params.append(int(student_filter))
    if status_filter in ("REGISTERED", "COMPLETED", "CANCELLED"):
        where.append("registration_status = %s")
        params.append(status_filter)
    records = db.query_all(f"""
        SELECT * FROM (
            SELECT cr.registration_id, st.student_id, st.name AS student_name,
                   c.course_code, c.course_name, c.course_type, s.semester_number,
                   cr.registration_date, cr.marks_obtained, cr.passing_mark_used, cr.result,
                   cr.registration_status, {rules.ATTEMPT_RANK_SQL} AS attempt_rank
            FROM course_registration cr
            JOIN student st ON st.student_id = cr.student_id
            JOIN course c ON c.course_id = cr.course_id
            JOIN semester s ON s.semester_id = cr.semester_id
        ) x {'WHERE ' + ' AND '.join(where) if where else ''}
        ORDER BY student_name, course_code, semester_number, registration_id""", params)
    students = db.query_all("""
        SELECT st.student_id, st.name, st.email, st.current_semester_id,
               p.program_name, d.department_name, se.semester_number
        FROM student st JOIN program p ON p.program_id = st.program_id
        JOIN department d ON d.department_id = st.department_id
        JOIN semester se ON se.semester_id = st.current_semester_id ORDER BY st.name""")
    courses = db.query_all("""
        SELECT c.course_id, c.course_code, c.course_name, c.course_type, d.department_name,
               s.semester_number, p.program_name
        FROM course c JOIN department d ON d.department_id = c.department_id
        JOIN semester s ON s.semester_id = c.semester_id
        JOIN program p ON p.program_id = c.program_id ORDER BY c.course_code""")
    semesters = db.query_all(OPTION_QUERIES["semesters"])
    return render_template(
        "admin_registrations.html", role="admin", item=navigation.find("admin", "registrations"),
        records=records, students=students, courses=courses, semesters=semesters,
        values=values or {}, student_filter=student_filter, status_filter=status_filter), status


@bp.route("/registrations", methods=["GET", "POST"], endpoint="registrations")
@admin_only
def registrations():
    if request.method == "GET":
        return _registration_page()
    action = request.form.get("action")
    try:
        if action == "create":
            rules.create_registration(
                v.choice_id(request.form.get("student_id"), "Student"),
                v.choice_id(request.form.get("course_id"), "Course"),
                v.choice_id(request.form.get("semester_id"), "Semester"))
            db.commit()
            flash("Course registration created.", "success")
        elif action in ("cancel", "restore"):
            registration_id = v.choice_id(request.form.get("registration_id"), "Registration")
            row = db.query_one("""SELECT student_id, course_id, semester_id, result, registration_status
                                  FROM course_registration WHERE registration_id = %s FOR UPDATE""", (registration_id,))
            if not row:
                raise ValueError("Registration not found.")
            if action == "cancel":
                if row["registration_status"] != "REGISTERED" or row["result"] != "PENDING":
                    raise ValueError("Only registrations that are still awaiting a result can be cancelled.")
                db.execute("UPDATE course_registration SET registration_status = 'CANCELLED' WHERE registration_id = %s",
                           (registration_id,))
                flash("Registration cancelled. It stays in the history.", "success")
            else:
                if row["registration_status"] != "CANCELLED":
                    raise ValueError("Only cancelled registrations can be restored.")
                rules.check_registration(row["student_id"], row["course_id"], row["semester_id"],
                                         exclude_registration_id=registration_id)
                db.execute("UPDATE course_registration SET registration_status = 'REGISTERED' WHERE registration_id = %s",
                           (registration_id,))
                flash("Registration restored.", "success")
            db.commit()
        else:
            raise ValueError("Unknown action.")
        return redirect(url_for("admin.registrations"))
    except ValueError as exc:                       # includes RegistrationError
        db.rollback()
        flash(str(exc), "error")
    except psycopg2.Error as exc:
        db.rollback()
        current_app.logger.exception("Registration action failed")
        flash(_db_message(exc, "Could not process the registration."), "error")
    return _registration_page(values=request.form.to_dict(), status=400)


from blueprints import admin_assign   # noqa: E402  (needs `bp` and `admin_only` defined above)
admin_assign.register(bp)
register_placeholders(bp, "admin")
