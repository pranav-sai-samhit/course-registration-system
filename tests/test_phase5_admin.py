"""Phase 5: admin CRUD for the six modules and course-registration management (live PostgreSQL)."""
import re
import threading

import pytest

import database as db
import security
from app import create_app
from conftest import PASSWORD, _exec, get_csrf


# ------------------------------------------------------------------ helpers
def rows(sql, params=()):
    conn = db.get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def one(sql, params=()):
    r = rows(sql, params)
    return r[0][0] if r else None


def flashes(response):
    html = response.get_data(as_text=True)
    return " ".join(re.findall(r'role="alert">\s*(.*?)\s*<button', html, flags=re.S))


@pytest.fixture()
def world(seeded):
    """seeded gives: program 1 B.Tech/dept 1 CSE/sems 1-3, students 1-2 (sem 1), faculty 1-2. Add more."""
    _exec("INSERT INTO department VALUES (2,'ECE',1),(3,'Physics',2)") if False else None
    _exec("INSERT INTO program VALUES (2,'PhD','PhD',5)")
    _exec("INSERT INTO department VALUES (2,'ECE',1),(3,'Physics',2)")
    _exec("INSERT INTO semester VALUES (4,2,1,1),(5,2,2,1)")
    _exec("""INSERT INTO course VALUES
        (1,'CS101','Intro to CS','CORE',1,1,1,40),
        (2,'CSE1','Elective One','ELECTIVE',1,1,1,NULL),
        (3,'CSE2','Elective Two','ELECTIVE',1,1,1,NULL),
        (4,'CSE3','Elective Three','ELECTIVE',1,1,1,NULL),
        (5,'CS201','Data Structures','CORE',1,1,2,NULL),
        (6,'EC101','Circuits','CORE',1,2,1,50),
        (7,'PH101','Research Methods','CORE',2,3,4,50),
        (8,'CS301','Algorithms','CORE',1,1,3,45)""")


@pytest.fixture()
def admin(client, login, world):
    login("admin", "admin@test.edu")
    token = get_csrf(client, "/admin/dashboard")

    class Admin:
        c = client

        @staticmethod
        def post(path, **data):
            return client.post(path, data={"csrf_token": token, **data})

        @staticmethod
        def get(path):
            return client.get(path)
    return Admin


def make_result(reg_id, marks, pmark, result):
    _exec("""UPDATE course_registration SET marks_obtained=%s, passing_mark_used=%s, result=%s,
             registration_status='COMPLETED' WHERE registration_id=%s""", (marks, pmark, result, reg_id))


def register(admin, student, course, semester):
    return admin.post("/admin/registrations", action="create", student_id=student, course_id=course, semester_id=semester)


# ===================================================== access & CSRF
def test_all_admin_pages_forbid_other_roles(client, login, world):
    login("student", "sam@test.edu")
    for path in ("/admin/students", "/admin/courses", "/admin/registrations", "/admin/students/1/edit"):
        assert client.get(path).status_code == 403
    token = get_csrf(client, "/student/dashboard")
    for path in ("/admin/students", "/admin/students/1/delete", "/admin/registrations"):
        assert client.post(path, data={"csrf_token": token}).status_code == 403


def test_admin_posts_need_csrf(admin):
    assert admin.c.post("/admin/programs", data={"program_name": "X", "program_type": "X", "duration_years": "2"}).status_code == 400
    assert admin.c.post("/admin/students/1/delete").status_code == 400
    assert one("SELECT COUNT(*) FROM student") == 2


# ===================================================== students
def new_student(**over):
    data = dict(name="Nia New", email="NIA@Test.edu", password="Strong-Pass-1", program_id="1",
                department_id="1", current_semester_id="1")
    data.update(over)
    return data


def test_student_crud_and_login(admin, app):
    r = admin.post("/admin/students", **new_student())
    assert r.status_code == 302
    sid = one("SELECT student_id FROM student WHERE name='Nia New'")
    stored = rows("SELECT email, password_hash FROM student WHERE student_id=%s", (sid,))[0]
    assert stored[0] == "nia@test.edu" and security.is_hashed(stored[1]) and "Strong-Pass-1" not in stored[1]
    assert "Nia New" in admin.get("/admin/students").get_data(as_text=True)
    # the new student can sign in
    c2 = app.test_client()
    tok = get_csrf(c2, "/student/login")
    assert c2.post("/student/login", data={"email": "nia@test.edu", "password": "Strong-Pass-1", "csrf_token": tok}).status_code == 302
    # edit without password keeps old hash; with password replaces it
    old = stored[1]
    admin.post(f"/admin/students/{sid}/edit", **new_student(name="Nia Renamed", password="", current_semester_id="2"))
    assert one("SELECT name FROM student WHERE student_id=%s", (sid,)) == "Nia Renamed"
    assert one("SELECT password_hash FROM student WHERE student_id=%s", (sid,)) == old
    assert one("SELECT current_semester_id FROM student WHERE student_id=%s", (sid,)) == 2
    admin.post(f"/admin/students/{sid}/edit", **new_student(password="Another-Pass-2"))
    assert one("SELECT password_hash FROM student WHERE student_id=%s", (sid,)) != old
    # delete
    assert admin.post(f"/admin/students/{sid}/delete").status_code == 302
    assert one("SELECT COUNT(*) FROM student WHERE student_id=%s", (sid,)) == 0


@pytest.mark.parametrize("override,message", [
    ({"name": ""}, "Student name is required"),
    ({"email": "not-an-email"}, "valid email"),
    ({"email": "sam@test.edu"}, "already uses this email"),
    ({"email": "SAM@TEST.EDU"}, "already uses this email"),
    ({"password": ""}, "Password is required"),
    ({"password": "short"}, "at least 8"),
    ({"program_id": ""}, "Select a program"),
    ({"department_id": "3"}, "same program"),            # PhD dept with B.Tech program
    ({"current_semester_id": "4"}, "same program"),      # PhD semester
    ({"name": "x" * 101}, "at most 100"),
])
def test_student_validation(admin, override, message):
    r = admin.post("/admin/students", **new_student(**override))
    assert r.status_code == 400 and message in flashes(r)
    assert one("SELECT COUNT(*) FROM student") == 2


def test_student_with_registrations_cannot_change_program_or_department(admin):
    register(admin, 1, 1, 1)
    r = admin.post("/admin/students/1/edit", name="Sam", email="sam@test.edu", password="", program_id="1",
                   department_id="2", current_semester_id="1")
    assert r.status_code == 400 and "cannot be changed" in flashes(r)
    # semester change is still allowed
    r = admin.post("/admin/students/1/edit", name="Sam", email="sam@test.edu", password="", program_id="1",
                   department_id="1", current_semester_id="2")
    assert r.status_code == 302


def test_delete_student_with_registration_is_blocked_and_data_kept(admin):
    register(admin, 1, 1, 1)
    r = admin.post("/admin/students/1/delete")
    assert "linked to other records" in flashes(admin.get("/admin/students"))
    assert one("SELECT COUNT(*) FROM student WHERE student_id=1") == 1
    assert one("SELECT COUNT(*) FROM course_registration") == 1


def test_edit_unknown_record(admin):
    assert admin.get("/admin/students/999/edit").status_code == 302
    assert "not found" in flashes(admin.get("/admin/students"))
    assert admin.post("/admin/students/999/delete").status_code == 302


def test_sql_injection_in_form_values_is_stored_literally(admin):
    evil = "x'); DROP TABLE student; --"
    admin.post("/admin/programs", program_name=evil, program_type="T", duration_years="2")
    assert one("SELECT COUNT(*) FROM student") == 2
    assert one("SELECT COUNT(*) FROM program WHERE program_name=%s", (evil,)) == 1
    assert "DROP TABLE" in admin.get("/admin/programs").get_data(as_text=True)      # escaped, not executed
    assert "<script>" not in admin.post("/admin/programs", program_name="<script>alert(1)</script>",
                                        program_type="T", duration_years="2").get_data(as_text=True)
    assert "&lt;script&gt;" in admin.get("/admin/programs").get_data(as_text=True)


# ===================================================== faculty
def test_faculty_crud_and_login(admin, app):
    assert admin.post("/admin/faculty", name="Gus Guru", email="gus@test.edu", password="Guru-Pass-123").status_code == 302
    fid = one("SELECT faculty_id FROM faculty WHERE email='gus@test.edu'")
    c2 = app.test_client()
    tok = get_csrf(c2, "/faculty/login")
    assert c2.post("/faculty/login", data={"email": "gus@test.edu", "password": "Guru-Pass-123", "csrf_token": tok}).status_code == 302
    r = admin.post("/admin/faculty", name="Dup", email="GUS@test.edu", password="Guru-Pass-123")
    assert r.status_code == 400 and "already uses" in flashes(r)
    admin.post(f"/admin/faculty/{fid}/edit", name="Gus G.", email="gus@test.edu", password="")
    assert one("SELECT name FROM faculty WHERE faculty_id=%s", (fid,)) == "Gus G."
    admin.post(f"/admin/faculty/{fid}/delete")
    assert one("SELECT COUNT(*) FROM faculty WHERE faculty_id=%s", (fid,)) == 0


def test_faculty_with_assignment_cannot_be_deleted(admin):
    _exec("INSERT INTO faculty_assignment VALUES (1,1,1,1,1,1,NULL,NULL)")
    admin.post("/admin/faculty/1/delete")
    assert one("SELECT COUNT(*) FROM faculty WHERE faculty_id=1") == 1
    assert "linked to other records" in flashes(admin.get("/admin/faculty"))


# ===================================================== programs / departments / semesters
def test_program_crud_and_rules(admin):
    assert admin.post("/admin/programs", program_name="M.Tech", program_type="M.Tech", duration_years="2").status_code == 302
    pid = one("SELECT program_id FROM program WHERE program_name='M.Tech'")
    for data, msg in [({"program_name": "m.tech"}, "already exists"), ({"duration_years": "0"}, "at least 1"),
                      ({"duration_years": "abc"}, "whole number"), ({"program_type": ""}, "required")]:
        form = dict(program_name="Other", program_type="X", duration_years="3"); form.update(data)
        r = admin.post("/admin/programs", **form)
        assert r.status_code == 400 and msg in flashes(r), data
    # PhD is a standalone program (seeded as its own row)
    assert one("SELECT program_type FROM program WHERE program_name='PhD'") == "PhD"
    # shrinking duration below an existing semester is refused
    admin.post("/admin/semesters", program_id=str(pid), semester_number="4")
    r = admin.post(f"/admin/programs/{pid}/edit", program_name="M.Tech", program_type="M.Tech", duration_years="1")
    assert r.status_code == 400 and "too short" in flashes(r)
    assert admin.post(f"/admin/programs/{pid}/edit", program_name="M.Tech", program_type="M.Tech", duration_years="3").status_code == 302


def test_department_rules(admin):
    assert admin.post("/admin/departments", department_name="Mech", program_id="1").status_code == 302
    r = admin.post("/admin/departments", department_name="mech", program_id="1")
    assert r.status_code == 400 and "already has a department" in flashes(r)
    assert admin.post("/admin/departments", department_name="Mech", program_id="2").status_code == 302   # other program OK
    r = admin.post("/admin/departments/1/edit", department_name="CSE", program_id="2")     # has students & courses
    assert r.status_code == 400 and "cannot be moved" in flashes(r)
    assert admin.post("/admin/departments/1/delete").status_code == 302
    assert one("SELECT COUNT(*) FROM department WHERE department_id=1") == 1                 # still in use


def test_semester_academic_year_is_computed_automatically(admin):
    for n, year in [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (6, 3), (7, 4), (8, 4)]:
        _exec("DELETE FROM semester WHERE program_id=1 AND semester_number=%s AND semester_id>3", (n,))
        if n > 3:
            assert admin.post("/admin/semesters", program_id="1", semester_number=str(n)).status_code == 302
        assert one("SELECT academic_year_number FROM semester WHERE program_id=1 AND semester_number=%s", (n,)) == year
    # a forged academic_year field is ignored
    _exec("DELETE FROM semester WHERE semester_number=8 AND program_id=1")
    admin.post("/admin/semesters", program_id="1", semester_number="8", academic_year_number="1")
    assert one("SELECT academic_year_number FROM semester WHERE program_id=1 AND semester_number=8") == 4


def test_semester_rules(admin):
    r = admin.post("/admin/semesters", program_id="1", semester_number="1")
    assert r.status_code == 400 and "already has that semester" in flashes(r)
    r = admin.post("/admin/semesters", program_id="1", semester_number="9")           # B.Tech = 4 years = 8 sems
    assert r.status_code == 400 and "at most 8" in flashes(r)
    r = admin.post("/admin/semesters", program_id="1", semester_number="0")
    assert r.status_code == 400
    r = admin.post("/admin/semesters/1/edit", program_id="1", semester_number="6")    # in use by students/courses
    assert r.status_code == 400 and "cannot be changed" in flashes(r)
    admin.post("/admin/semesters/1/delete")
    assert one("SELECT COUNT(*) FROM semester WHERE semester_id=1") == 1


# ===================================================== courses
def course_form(**over):
    data = dict(course_code="cs777", course_name="New Course", course_type="CORE", program_id="1",
                department_id="1", semester_id="2", passing_mark="")
    data.update(over)
    return data


def test_course_create_without_passing_mark(admin):
    assert admin.post("/admin/courses", **course_form()).status_code == 302
    assert rows("SELECT course_code, passing_mark FROM course WHERE course_name='New Course'")[0] == ("CS777", None)
    assert one("SELECT COUNT(*) FROM passing_mark_approval") == 0            # nothing to log


def test_course_create_with_initial_passing_mark_is_logged(admin):
    admin.post("/admin/courses", **course_form(course_code="CS778", passing_mark="42.5"))
    cid = one("SELECT course_id FROM course WHERE course_code='CS778'")
    assert float(one("SELECT passing_mark FROM course WHERE course_id=%s", (cid,))) == 42.5
    log = rows("""SELECT proposed_passing_mark, faculty_id, admin_id, faculty_status, admin_status, approval_date
                  FROM passing_mark_approval WHERE course_id=%s""", (cid,))
    assert len(log) == 1 and float(log[0][0]) == 42.5 and log[0][1] is None and log[0][2] == 1
    assert log[0][4] == "APPROVED" and log[0][5] is not None


@pytest.mark.parametrize("override,message", [
    ({"course_code": "CS101"}, "already uses this course code"),
    ({"course_code": "cs101"}, "already uses this course code"),
    ({"course_type": "OPTIONAL"}, "CORE or ELECTIVE"),
    ({"department_id": "3"}, "same program"),
    ({"semester_id": "4"}, "same program"),
    ({"passing_mark": "101"}, "between 0 and 100"),
    ({"passing_mark": "-1"}, "between 0 and 100"),
    ({"passing_mark": "abc"}, "must be a number"),
    ({"passing_mark": "40.123"}, "two decimal"),
    ({"course_name": ""}, "Course name is required"),
])
def test_course_validation(admin, override, message):
    r = admin.post("/admin/courses", **course_form(**override))
    assert r.status_code == 400 and message in flashes(r)
    assert one("SELECT COUNT(*) FROM course") == 8


def test_course_edit_cannot_change_passing_mark(admin):
    admin.post("/admin/courses/1/edit", **course_form(course_code="CS101", course_name="Renamed", semester_id="1",
                                                      passing_mark="99"))
    assert one("SELECT course_name FROM course WHERE course_id=1") == "Renamed"
    assert float(one("SELECT passing_mark FROM course WHERE course_id=1")) == 40       # forged field ignored
    assert one("SELECT COUNT(*) FROM passing_mark_approval") == 0
    html = admin.get("/admin/courses/1/edit").get_data(as_text=True)
    assert "Passing Mark Approvals page" in html


def test_course_with_registrations_is_locked(admin):
    register(admin, 1, 1, 1)
    r = admin.post("/admin/courses/1/edit", **course_form(course_code="CS101", course_type="ELECTIVE", semester_id="1"))
    assert r.status_code == 400 and "cannot be changed" in flashes(r)
    r = admin.post("/admin/courses/1/edit", **course_form(course_code="CS101", course_name="Rename ok", semester_id="1"))
    assert r.status_code == 302
    admin.post("/admin/courses/1/delete")
    assert one("SELECT COUNT(*) FROM course WHERE course_id=1") == 1


# ===================================================== registrations - happy path & rules
def test_cannot_register_for_a_semester_not_reached_yet(admin):
    r = register(admin, 1, 5, 2)          # student 1 is in semester 1; course 5 is offered in semester 2
    assert r.status_code == 400 and "not reached semester 2" in flashes(r)
    assert one("SELECT COUNT(*) FROM course_registration") == 0
    _exec("UPDATE student SET current_semester_id=2 WHERE student_id=1")
    assert register(admin, 1, 5, 2).status_code == 302            # now allowed, and no passing mark needed
    assert one("SELECT passing_mark FROM course WHERE course_id=5") is None


def test_registration_stores_no_passing_mark_snapshot(admin):
    r = register(admin, 1, 1, 1)
    assert r.status_code == 302
    assert rows("SELECT result, registration_status, marks_obtained, passing_mark_used FROM course_registration")[0] \
        == ("PENDING", "REGISTERED", None, None)
    # and a course with NO official passing mark registers fine
    assert one("SELECT passing_mark FROM course WHERE course_id=2") is None
    assert register(admin, 1, 2, 1).status_code == 302


def test_registration_ids_are_sequential_and_unique(admin):
    register(admin, 1, 1, 1); register(admin, 2, 1, 1); register(admin, 1, 2, 1)
    assert [r[0] for r in rows("SELECT registration_id FROM course_registration ORDER BY 1")] == [1, 2, 3]


def test_duplicate_registration_refused(admin):
    register(admin, 1, 1, 1)
    r = register(admin, 1, 1, 1)
    assert r.status_code == 400 and "already registered" in flashes(r)
    assert one("SELECT COUNT(*) FROM course_registration") == 1


def test_wrong_department_program_and_semester_refused(admin):
    r = register(admin, 1, 6, 1);  assert "department" in flashes(r)         # ECE course for CSE student
    r = register(admin, 1, 7, 1);  assert "program" in flashes(r)            # PhD course
    r = register(admin, 1, 1, 4);  assert "semester does not belong" in flashes(r)
    r = register(admin, 1, 5, 1);  assert "first time only in the semester it is offered" in flashes(r)
    assert one("SELECT COUNT(*) FROM course_registration") == 0


@pytest.mark.parametrize("field", ["student_id", "course_id", "semester_id"])
def test_registration_requires_selections(admin, field):
    data = dict(action="create", student_id="1", course_id="1", semester_id="1"); data[field] = ""
    r = admin.post("/admin/registrations", **data)
    assert r.status_code == 400 and "Select a" in flashes(r)


def test_registration_unknown_ids(admin):
    assert register(admin, 99, 1, 1).status_code == 400
    assert register(admin, 1, 99, 1).status_code == 400
    assert register(admin, 1, 1, 99).status_code == 400
    assert register(admin, "abc", 1, 1).status_code == 400


def test_elective_limit_is_two_per_semester(admin):
    assert register(admin, 1, 2, 1).status_code == 302
    assert register(admin, 1, 3, 1).status_code == 302
    r = register(admin, 1, 4, 1)
    assert r.status_code == 400 and "at most 2 elective" in flashes(r)
    assert register(admin, 1, 1, 1).status_code == 302                      # core is unaffected
    assert register(admin, 2, 4, 1).status_code == 302                      # other students unaffected
    # cancelling one elective frees a slot
    first = one("SELECT registration_id FROM course_registration WHERE student_id=1 AND course_id=2")
    admin.post("/admin/registrations", action="cancel", registration_id=str(first))
    assert register(admin, 1, 4, 1).status_code == 302


def test_elective_limit_holds_under_concurrent_requests(admin, world):
    register(admin, 1, 2, 1)                                  # one elective already taken
    results = []
    barrier = threading.Barrier(2)

    def worker(course_id):
        c = create_app({"TESTING": True}).test_client()
        tok = get_csrf(c, "/admin/login")
        c.post("/admin/login", data={"email": "admin@test.edu", "password": PASSWORD, "csrf_token": tok})
        tok = get_csrf(c, "/admin/dashboard")
        barrier.wait()
        results.append(c.post("/admin/registrations", data={
            "csrf_token": tok, "action": "create", "student_id": "1", "course_id": str(course_id), "semester_id": "1"
        }).status_code)

    threads = [threading.Thread(target=worker, args=(cid,)) for cid in (3, 4)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert sorted(results) == [302, 400]
    assert one("""SELECT COUNT(*) FROM course_registration cr JOIN course c USING (course_id)
                  WHERE student_id=1 AND c.course_type='ELECTIVE'""") == 2


def test_passed_course_cannot_be_registered_again(admin):
    _exec("UPDATE student SET current_semester_id=3 WHERE student_id=1")
    register(admin, 1, 1, 1)
    make_result(1, 80, 40, "PASS")
    for sem in ("2", "3"):
        r = register(admin, 1, 1, sem)
        assert r.status_code == 400 and "already passed" in flashes(r)
    assert one("SELECT COUNT(*) FROM course_registration") == 1


def test_failed_course_reattempt_rules_and_history(admin):
    _exec("UPDATE student SET current_semester_id=3 WHERE student_id=1")
    register(admin, 1, 1, 1)
    r = register(admin, 1, 1, 2)                              # attempt 1 still PENDING
    assert r.status_code == 400 and "no result yet" in flashes(r)
    make_result(1, 20, 40, "FAIL")
    r = register(admin, 1, 1, 1)
    assert r.status_code == 400                               # same semester
    assert register(admin, 1, 1, 2).status_code == 302        # later semester: allowed
    assert one("SELECT COUNT(*) FROM course_registration WHERE student_id=1 AND course_id=1") == 2
    # attempt 1 untouched
    assert rows("SELECT marks_obtained, passing_mark_used, result FROM course_registration WHERE registration_id=1") \
        == [(20, 40, "FAIL")]
    # second failure, third attempt allowed too (multiple reattempts)
    make_result(2, 30, 40, "FAIL")
    assert register(admin, 1, 1, 3).status_code == 302
    assert one("SELECT COUNT(*) FROM course_registration WHERE student_id=1 AND course_id=1") == 3
    # pass on the third attempt -> no more attempts, and the message says why
    make_result(3, 70, 40, "PASS")
    assert "already passed" in flashes(register(admin, 1, 1, 3))
    assert "already passed" in flashes(register(admin, 1, 1, 2))


def test_cannot_reattempt_in_an_earlier_semester_than_the_latest_attempt(admin):
    _exec("UPDATE student SET current_semester_id=3 WHERE student_id=1")
    _exec("INSERT INTO course_registration (registration_id, student_id, course_id, semester_id, marks_obtained,"
          " passing_mark_used, result, registration_status) VALUES (1,1,8,3,10,45,'FAIL','COMPLETED')")
    r = register(admin, 1, 8, 2)
    assert r.status_code == 400 and "later semester" in flashes(r)
    assert one("SELECT COUNT(*) FROM course_registration") == 1


def test_reattempt_is_allowed_even_if_semester_not_current_offering(admin):
    _exec("UPDATE student SET current_semester_id=3 WHERE student_id=1")
    """Reattempt happens in a later semester than the one the course is offered in."""
    register(admin, 1, 1, 1); make_result(1, 10, 40, "FAIL")
    assert register(admin, 1, 1, 3).status_code == 302          # skipping sem 2 is fine


def test_reattempt_of_elective_counts_toward_elective_limit(admin):
    _exec("UPDATE student SET current_semester_id=3 WHERE student_id=1")
    register(admin, 1, 2, 1); make_result(1, 10, 40, "FAIL")
    register(admin, 1, 3, 1); make_result(2, 90, 40, "PASS")
    assert register(admin, 1, 2, 2).status_code == 302          # reattempt of failed elective in sem 2
    # a second elective in semester 2 is not possible: new electives can only be taken in their offering semester
    assert register(admin, 1, 4, 2).status_code == 400


# ===================================================== cancel / restore
def test_cancel_keeps_history_and_blocks_later_duplicates(admin):
    register(admin, 1, 1, 1)
    assert admin.post("/admin/registrations", action="cancel", registration_id="1").status_code == 302
    assert rows("SELECT registration_status, result FROM course_registration") == [("CANCELLED", "PENDING")]
    r = register(admin, 1, 1, 1)
    assert r.status_code == 400 and "Restore that registration" in flashes(r)
    assert admin.post("/admin/registrations", action="restore", registration_id="1").status_code == 302
    assert one("SELECT registration_status FROM course_registration") == "REGISTERED"


def test_cannot_cancel_completed_or_restore_active(admin):
    register(admin, 1, 1, 1); make_result(1, 70, 40, "PASS")
    r = admin.post("/admin/registrations", action="cancel", registration_id="1")
    assert r.status_code == 400 and "awaiting a result" in flashes(r)
    r = admin.post("/admin/registrations", action="restore", registration_id="1")
    assert r.status_code == 400 and "Only cancelled" in flashes(r)
    assert admin.post("/admin/registrations", action="cancel", registration_id="99").status_code == 400
    assert admin.post("/admin/registrations", action="bogus").status_code == 400


def test_restore_revalidates_rules(admin):
    register(admin, 1, 2, 1); register(admin, 1, 3, 1)
    admin.post("/admin/registrations", action="cancel", registration_id="1")
    register(admin, 1, 4, 1)                                    # takes the freed elective slot
    r = admin.post("/admin/registrations", action="restore", registration_id="1")
    assert r.status_code == 400 and "at most 2 elective" in flashes(r)
    assert one("SELECT registration_status FROM course_registration WHERE registration_id=1") == "CANCELLED"


# ===================================================== listing
def test_registration_list_shows_all_attempts_with_labels(admin):
    _exec("UPDATE student SET current_semester_id=3 WHERE student_id=1")
    register(admin, 1, 1, 1); make_result(1, 10, 40, "FAIL")
    register(admin, 1, 1, 2)
    register(admin, 2, 1, 1); admin.post("/admin/registrations", action="cancel", registration_id="3")
    html = admin.get("/admin/registrations").get_data(as_text=True)
    assert html.count("<td>Previous</td>") == 1 and html.count("<td>Current</td>") == 1 and html.count("<td>Cancelled</td>") == 2   # Status and Attempt columns
    assert "Sam Student" in html and "Sue Student" in html


def test_registration_list_filters(admin):
    register(admin, 1, 1, 1); register(admin, 2, 1, 1)
    admin.post("/admin/registrations", action="cancel", registration_id="2")
    html = admin.get("/admin/registrations?student_id=1").get_data(as_text=True)
    assert "<td>Sam Student</td>" in html and "<td>Sue Student</td>" not in html
    html = admin.get("/admin/registrations?status=CANCELLED").get_data(as_text=True)
    assert "<td>Sue Student</td>" in html and "<td>Sam Student</td>" not in html
    assert admin.get("/admin/registrations?status=BOGUS&student_id=abc").status_code == 200    # bad filters ignored


def test_empty_states(client, login, seeded):
    login("admin", "admin@test.edu")
    assert "No registrations match" in client.get("/admin/registrations").get_data(as_text=True)
    assert "No courses have been added" in client.get("/admin/courses").get_data(as_text=True)


def test_failed_post_keeps_form_values(admin):
    r = admin.post("/admin/courses", **course_form(course_code="CS101", course_name="Kept Name"))
    assert r.status_code == 400 and 'value="Kept Name"' in r.get_data(as_text=True)


def test_database_still_has_exactly_ten_tables(admin):
    assert one("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'") == 10
