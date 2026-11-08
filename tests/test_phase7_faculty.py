"""Phase 7: faculty assignment (course + student level), faculty pages, marks entry, results."""
import pytest

from conftest import PASSWORD, _exec, get_csrf
from test_phase5_admin import admin, flashes, one, rows, world, make_result, register  # noqa: F401


def course_assign(admin, faculty=(1,), **over):
    data = dict(program_id=1, department_id=1, academic_year=1, semester_id=1, course_id=1)
    data.update(over)
    return admin.c.post("/admin/faculty-assignments/course-level",
                        data={"csrf_token": get_csrf(admin.c, "/admin/dashboard"), **data, "faculty_ids": list(faculty)},
                        follow_redirects=True)


def student_assign(admin, reg, faculty=(1,), student=1):
    return admin.c.post("/admin/faculty-assignments/student-level/save",
                        data={"csrf_token": get_csrf(admin.c, "/admin/dashboard"), "registration_id": reg,
                              "student_id": student, "faculty_ids": list(faculty)}, follow_redirects=True)


def faculty_client(app, email="fay@test.edu"):
    c = app.test_client()
    t = get_csrf(c, "/faculty/login")
    c.post("/faculty/login", data={"email": email, "password": PASSWORD, "csrf_token": t})
    return c


def fpost(c, path, **data):
    return c.post(path, data={"csrf_token": get_csrf(c, "/faculty/dashboard"), **data}, follow_redirects=True)


# ---------------------------------------------------------- course level
def test_landing_has_two_sections(admin):
    html = admin.get("/admin/faculty-assignments").get_data(as_text=True)
    assert "Course-level faculty assignment" in html and "Student-level faculty assignment" in html


def test_course_level_multiple_faculty_row_shape(admin):
    r = course_assign(admin, faculty=(1, 2))
    assert "Assigned:" in flashes(r)
    assert rows("""SELECT faculty_id, program_id, department_id, semester_id, course_id, student_id, registration_id
                   FROM faculty_assignment ORDER BY faculty_id""") == \
        [(1, 1, 1, 1, 1, None, None), (2, 1, 1, 1, 1, None, None)]


@pytest.mark.parametrize("over,msg", [
    ({"course_id": 6}, "department"),
    ({"course_id": 5}, "semester"),
    ({"program_id": 2}, "program"),
    ({"academic_year": 2}, "academic year"),
    ({"course_id": ""}, "Select a course"),
    ({"department_id": ""}, "Select a department"),
])
def test_course_level_validation(admin, over, msg):
    r = course_assign(admin, **over)
    assert msg.lower() in flashes(r).lower()
    assert one("SELECT COUNT(*) FROM faculty_assignment") == 0


def test_course_level_requires_faculty_and_rejects_duplicates(admin):
    assert "at least one faculty" in flashes(course_assign(admin, faculty=()))
    course_assign(admin)
    assert "already assigned" in flashes(course_assign(admin))
    assert one("SELECT COUNT(*) FROM faculty_assignment") == 1
    assert "does not exist" in flashes(course_assign(admin, faculty=(99,)))


def test_course_level_page_lists_assignments(admin):
    course_assign(admin)
    html = admin.get("/admin/faculty-assignments/course-level").get_data(as_text=True)
    assert "Fay Faculty" in html and "CS101" in html


# --------------------------------------------------------- student level
def test_student_level_flow_and_row_shape(admin):
    register(admin, 1, 1, 1)
    course_assign(admin, faculty=(1, 2))
    html = admin.get("/admin/faculty-assignments/student-level?student_id=1").get_data(as_text=True)
    assert "CS101" in html and "Sue Student" in html           # student list present; registration shown
    html = admin.get("/admin/faculty-assignments/student-level?student_id=1&registration_id=1").get_data(as_text=True)
    assert "Fay Faculty" in html and "Fred Faculty" in html
    assert "Assigned:" in flashes(student_assign(admin, 1, faculty=(1, 2)))
    assert rows("""SELECT faculty_id, program_id, department_id, semester_id, course_id, student_id, registration_id
                   FROM faculty_assignment WHERE student_id IS NOT NULL ORDER BY faculty_id""") == \
        [(1, 1, 1, 1, 1, 1, 1), (2, 1, 1, 1, 1, 1, 1)]


def test_student_level_requires_faculty_on_course(admin):
    register(admin, 1, 1, 1)
    course_assign(admin, faculty=(1,))
    assert "not assigned to this course" in flashes(student_assign(admin, 1, faculty=(2,)))
    assert one("SELECT COUNT(*) FROM faculty_assignment WHERE student_id IS NOT NULL") == 0


def test_student_level_rejects_duplicates_cancelled_and_unknown(admin):
    register(admin, 1, 1, 1)
    course_assign(admin)
    student_assign(admin, 1)
    assert "already assigned" in flashes(student_assign(admin, 1))
    assert "valid registration" in flashes(student_assign(admin, 99))
    _exec("UPDATE course_registration SET registration_status='CANCELLED'")
    assert "cancelled" in flashes(student_assign(admin, 1, faculty=(1,))).lower()


def test_reattempt_is_assigned_separately(admin):
    _exec("UPDATE student SET current_semester_id=2 WHERE student_id=1")
    register(admin, 1, 1, 1)
    course_assign(admin)
    student_assign(admin, 1)
    make_result(1, 10, 40, "FAIL")
    register(admin, 1, 1, 2)                                   # reattempt = registration 2
    student_assign(admin, 2)
    assert rows("SELECT registration_id, semester_id FROM faculty_assignment WHERE student_id IS NOT NULL "
                "ORDER BY registration_id") == [(1, 1), (2, 2)]


def test_remove_rules(admin):
    register(admin, 1, 1, 1)
    course_assign(admin)
    student_assign(admin, 1)
    course_row = one("SELECT assignment_id FROM faculty_assignment WHERE student_id IS NULL")
    r = admin.post(f"/admin/faculty-assignments/{course_row}/remove", level="course")
    assert one("SELECT COUNT(*) FROM faculty_assignment") == 2          # blocked while student-level exists
    stu_row = one("SELECT assignment_id FROM faculty_assignment WHERE student_id IS NOT NULL")
    admin.post(f"/admin/faculty-assignments/{stu_row}/remove", level="student", student_id=1)
    admin.post(f"/admin/faculty-assignments/{course_row}/remove", level="course")
    assert one("SELECT COUNT(*) FROM faculty_assignment") == 0


def test_assignment_pages_need_admin_and_csrf(admin, client):
    assert client.post("/admin/faculty-assignments/course-level", data={"course_id": 1}).status_code == 400


# --------------------------------------------------------------- faculty
@pytest.fixture()
def setup(admin, app):
    """Sam registered for CS101 and CSE1; Sue for CS101. Fay teaches both courses but is assigned only
    to Sam's CS101; Fred teaches CS101 and is assigned to Sue's."""
    for s, c in ((1, 1), (1, 2), (2, 1)):
        register(admin, s, c, 1)
    course_assign(admin, faculty=(1, 2))
    course_assign(admin, faculty=(1,), course_id=2)
    student_assign(admin, 1, faculty=(1,), student=1)         # reg 1 = Sam CS101 -> Fay
    student_assign(admin, 3, faculty=(2,), student=2)         # reg 3 = Sue CS101 -> Fred
    return faculty_client(app)


def test_faculty_sees_only_assigned_courses_and_students(setup):
    c = setup
    html = c.get("/faculty/courses").get_data(as_text=True)
    assert "CS101" in html and "CSE1" in html and "Not set" in html
    html = c.get("/faculty/students").get_data(as_text=True)
    assert "Sam Student" in html and "Sue Student" not in html
    assert "CSE1" not in html            # course-level only: Sam's CSE1 registration is not assigned to Fay


def test_faculty_marks_pass_fail_and_snapshot(setup, app):
    c = setup
    r = fpost(c, "/faculty/marks/save", registration_id=1, marks="55.5")
    assert "PASS" in flashes(r)
    assert rows("SELECT marks_obtained, passing_mark_used, result, registration_status FROM course_registration "
                "WHERE registration_id=1")[0] == (55.5, 40, "PASS", "COMPLETED")
    # later change of the official mark does not touch the stored attempt
    _exec("UPDATE course SET passing_mark=90 WHERE course_id=1")
    assert rows("SELECT passing_mark_used, result FROM course_registration WHERE registration_id=1") == [(40, "PASS")]


def test_fail_boundary(setup):
    fpost(setup, "/faculty/marks/save", registration_id=1, marks="39.99")
    assert one("SELECT result FROM course_registration WHERE registration_id=1") == "FAIL"


def test_marks_cannot_be_overwritten_by_faculty(setup):
    fpost(setup, "/faculty/marks/save", registration_id=1, marks="10")
    r = fpost(setup, "/faculty/marks/save", registration_id=1, marks="99")
    assert "already been entered" in flashes(r)
    assert one("SELECT marks_obtained FROM course_registration WHERE registration_id=1") == 10


@pytest.mark.parametrize("marks", ["", "abc", "-1", "100.01", "101", "5.123"])
def test_marks_validation(setup, marks):
    r = fpost(setup, "/faculty/marks/save", registration_id=1, marks=marks)
    assert flashes(r)
    assert one("SELECT result FROM course_registration WHERE registration_id=1") == "PENDING"


def test_faculty_cannot_grade_unassigned_registration(setup):
    r = fpost(setup, "/faculty/marks/save", registration_id=3, marks="80")      # Sue's, assigned to Fred
    assert "not assigned to you" in flashes(r)
    r = fpost(setup, "/faculty/marks/save", registration_id=2, marks="80")      # Sam's CSE1, course-level only
    assert "not assigned to you" in flashes(r)
    assert one("SELECT COUNT(*) FROM course_registration WHERE result <> 'PENDING'") == 0


def test_marks_need_official_passing_mark(admin, app):
    register(admin, 1, 2, 1)                                   # CSE1 has no passing mark
    course_assign(admin, faculty=(1,), course_id=2)
    student_assign(admin, 1, faculty=(1,), student=1)
    c = faculty_client(app)
    page = c.get("/faculty/marks").get_data(as_text=True)
    assert "No official passing mark is set" in page and "Passing Mark Requests" in page
    r = fpost(c, "/faculty/marks/save", registration_id=1, marks="50")          # forced POST is refused too
    assert "No official passing mark" in flashes(r)
    assert rows("SELECT marks_obtained, passing_mark_used, result FROM course_registration") == [(None, None, "PENDING")]


def test_faculty_cannot_grade_cancelled_registration(setup):
    _exec("UPDATE course_registration SET registration_status='CANCELLED' WHERE registration_id=1")
    assert "Sam Student" not in setup.get("/faculty/students").get_data(as_text=True)
    assert "cancelled" in flashes(fpost(setup, "/faculty/marks/save", registration_id=1, marks="50"))


def test_faculty_results_page_scoped_and_labels(setup):
    fpost(setup, "/faculty/marks/save", registration_id=1, marks="70")
    html = setup.get("/faculty/results").get_data(as_text=True)
    assert "Sam Student" in html and "70.00" in html and "PASS" in html and "Sue Student" not in html


def test_faculty_marks_need_csrf_and_role(setup, app):
    assert setup.post("/faculty/marks/save", data={"registration_id": 1, "marks": "50"}).status_code == 400
    s = app.test_client()
    s.post("/student/login", data={"email": "sam@test.edu", "password": PASSWORD,
                                   "csrf_token": get_csrf(s, "/student/login")})
    assert s.get("/faculty/marks").status_code == 403


def test_admin_marks_entry_and_correction_keeps_snapshot(admin, setup):
    r = admin.c.post("/admin/registrations/3/marks", data={"csrf_token": get_csrf(admin.c, "/admin/dashboard"),
                                                           "marks": "30"}, follow_redirects=True)
    assert "FAIL" in flashes(r)
    _exec("UPDATE course SET passing_mark=10 WHERE course_id=1")
    admin.c.post("/admin/registrations/3/marks", data={"csrf_token": get_csrf(admin.c, "/admin/dashboard"),
                                                       "marks": "35"}, follow_redirects=True)
    assert rows("SELECT marks_obtained, passing_mark_used, result FROM course_registration WHERE registration_id=3") \
        == [(35, 40, "FAIL")]
    assert admin.get("/admin/registrations/3/marks").status_code == 200
    assert "not found" in flashes(admin.c.get("/admin/registrations/99/marks", follow_redirects=True))


def test_admin_marks_refused_without_passing_mark(admin):
    register(admin, 1, 2, 1)
    r = admin.c.post("/admin/registrations/1/marks", data={"csrf_token": get_csrf(admin.c, "/admin/dashboard"),
                                                           "marks": "50"})
    assert r.status_code == 400 and "No official passing mark" in r.get_data(as_text=True)


def test_phase7_pages_are_real(setup):
    for p in ("courses", "students", "marks", "results"):
        assert "not available yet" not in setup.get(f"/faculty/{p}").get_data(as_text=True)
