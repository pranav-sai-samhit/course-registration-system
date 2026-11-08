"""Phase 6: student self-service - available courses, registration, attempts, marks, results."""
import re

import pytest

from conftest import _exec, get_csrf
from test_phase5_admin import flashes, one, rows, world, make_result  # noqa: F401  (fixtures)


@pytest.fixture()
def sam(client, login, world):
    """Signed-in student 1 (semester 1) in the Phase 5 'world'."""
    login("student", "sam@test.edu")

    class S:
        c = client

        @staticmethod
        def get(path):
            return client.get(path)

        @staticmethod
        def register(course_id, **extra):
            token = get_csrf(client, "/student/available-courses")
            return client.post("/student/available-courses/register",
                               data={"csrf_token": token, "course_id": course_id, **extra})
    return S


def codes(html, section_title):
    """Course codes listed in the card whose header contains section_title."""
    start = html.index(section_title)
    nxt = html.find('card-header', start + 10)
    chunk = html[start: nxt if nxt != -1 else len(html)]
    return re.findall(r"<td>([A-Z]{2,3}\d?[0-9A-Z]*)</td>", chunk)


# ------------------------------------------------------------ available
def test_available_courses_are_program_department_semester_filtered(sam):
    html = sam.get("/student/available-courses").get_data(as_text=True)
    got = set(codes(html, "Courses offered this semester"))
    # semester 1, program 1, dept 1: CS101 + three electives. Not: EC101 (other dept), CS201 (sem 2),
    # CS301 (sem 3), PH101 (other program)
    assert got == {"CS101", "CSE1", "CSE2", "CSE3"}


def test_passing_mark_is_not_needed_to_register(sam):
    assert one("SELECT passing_mark FROM course WHERE course_id=2") is None      # elective without mark
    r = sam.register(2)
    assert r.status_code == 302
    assert rows("SELECT student_id, course_id, semester_id, passing_mark_used, result, registration_status "
                "FROM course_registration") == [(1, 2, 1, None, "PENDING", "REGISTERED")]


def test_register_for_available_course_and_it_leaves_the_list(sam):
    assert sam.register(1).status_code == 302
    html = sam.get("/student/available-courses").get_data(as_text=True)
    assert "CS101" not in codes(html, "Courses offered this semester")
    assert one("SELECT COUNT(*) FROM course_registration WHERE student_id=1") == 1


def test_duplicate_registration_refused(sam):
    sam.register(1)
    token = get_csrf(sam.c, "/student/available-courses")
    r = sam.c.post("/student/available-courses/register", data={"csrf_token": token, "course_id": 1},
                   follow_redirects=True)
    assert "already registered" in flashes(r) or "no result yet" in flashes(r)
    assert one("SELECT COUNT(*) FROM course_registration") == 1


def test_elective_limit_shown_and_enforced(sam):
    sam.register(2)
    sam.register(3)
    html = sam.get("/student/available-courses").get_data(as_text=True)
    assert "2 of 2" in html and "Elective limit reached" in html
    sam.register(4)
    assert one("SELECT COUNT(*) FROM course_registration") == 2
    # a core course is unaffected by the elective limit
    assert sam.register(1).status_code == 302
    assert one("SELECT COUNT(*) FROM course_registration") == 3


@pytest.mark.parametrize("course_id,fragment", [
    (6, "department"),        # other department
    (7, "program"),           # other program
    (5, "first time only in the semester it is offered"),   # semester 2 course while in semester 1
    (8, "first time only in the semester it is offered"),
])
def test_cannot_register_unavailable_courses_by_posting_ids(sam, course_id, fragment):
    token = get_csrf(sam.c, "/student/available-courses")
    r = sam.c.post("/student/available-courses/register", data={"csrf_token": token, "course_id": course_id},
                   follow_redirects=True)
    assert fragment in flashes(r)
    assert one("SELECT COUNT(*) FROM course_registration") == 0


def test_error_message_is_shown_for_forbidden_course(sam):
    token = get_csrf(sam.c, "/student/available-courses")
    r = sam.c.post("/student/available-courses/register", data={"csrf_token": token, "course_id": 6},
                   follow_redirects=True)
    assert "department" in flashes(r)


def test_register_requires_valid_course_id(sam):
    token = get_csrf(sam.c, "/student/available-courses")
    for bad in ("", "abc", "999"):
        r = sam.c.post("/student/available-courses/register",
                       data={"csrf_token": token, "course_id": bad}, follow_redirects=True)
        assert flashes(r), bad
    assert one("SELECT COUNT(*) FROM course_registration") == 0


def test_student_and_semester_cannot_be_forged_in_the_form(sam):
    sam.register(1, student_id=2, semester_id=2)
    assert rows("SELECT student_id, semester_id FROM course_registration") == [(1, 1)]


def test_register_needs_csrf_and_student_role(client, login, world):
    login("student", "sam@test.edu")
    assert client.post("/student/available-courses/register", data={"course_id": 1}).status_code == 400
    anon = client.application.test_client()                      # signed out: sent to the student login
    r = anon.post("/student/available-courses/register", data={"course_id": 1})
    assert r.status_code == 400 or r.headers["Location"].endswith("/student/login")
    other = client.application.test_client()                     # a faculty member must get 403
    token = get_csrf(other, "/faculty/login")
    other.post("/faculty/login", data={"email": "fay@test.edu", "password": "Test-Pass-123", "csrf_token": token})
    token = get_csrf(other, "/faculty/dashboard")
    assert other.post("/student/available-courses/register",
                      data={"csrf_token": token, "course_id": 1}).status_code == 403
    assert one("SELECT COUNT(*) FROM course_registration") == 0


# ---------------------------------------------------------- reattempts
def advance(student_id, semester_id):
    _exec("UPDATE student SET current_semester_id=%s WHERE student_id=%s", (semester_id, student_id))


def test_failed_course_reappears_only_in_a_later_semester_and_history_is_kept(sam):
    sam.register(1)
    make_result(1, 20, 40, "FAIL")
    # same semester: not offered again; shown as "waiting"
    html = sam.get("/student/available-courses").get_data(as_text=True)
    assert "CS101" not in codes(html, "Failed courses you can reattempt")
    assert "reattempt opens next semester" in sam.get("/student/results").get_data(as_text=True)
    assert sam.register(1).status_code == 302
    assert one("SELECT COUNT(*) FROM course_registration") == 1
    # next semester: eligible
    advance(1, 2)
    html = sam.get("/student/available-courses").get_data(as_text=True)
    assert "CS101" in codes(html, "Failed courses you can reattempt")
    assert "Reattempt" in html
    sam.register(1)
    assert rows("SELECT registration_id, semester_id, result FROM course_registration ORDER BY 1") == \
        [(1, 1, "FAIL"), (2, 2, "PENDING")]
    # attempt 1 untouched
    assert rows("SELECT marks_obtained, passing_mark_used FROM course_registration WHERE registration_id=1") == [(20, 40)]


def test_multiple_reattempts_then_pass_blocks_further_registration(sam):
    sam.register(1); make_result(1, 10, 40, "FAIL")
    advance(1, 2); sam.register(1); make_result(2, 15, 40, "FAIL")
    advance(1, 3); sam.register(1)
    assert one("SELECT COUNT(*) FROM course_registration WHERE student_id=1 AND course_id=1") == 3
    make_result(3, 90, 40, "PASS")
    html = sam.get("/student/available-courses").get_data(as_text=True)
    assert "CS101" not in html.split("Failed courses you can reattempt")[0].split("Courses offered")[1]
    sam.register(1)
    assert one("SELECT COUNT(*) FROM course_registration WHERE student_id=1 AND course_id=1") == 3


def test_pending_attempt_blocks_another_attempt(sam):
    sam.register(1)
    advance(1, 2)
    html = sam.get("/student/available-courses").get_data(as_text=True)
    assert "CS101" not in html.split("Failed courses you can reattempt")[1]
    sam.register(1)
    assert one("SELECT COUNT(*) FROM course_registration") == 1


def test_reattempt_of_elective_counts_toward_limit(sam):
    sam.register(2); make_result(1, 5, 40, "FAIL")
    advance(1, 2)
    # semester 2 offers no electives of its own in this data set; reattempt is the only elective
    sam.register(2)
    sam.register(3)          # CSE2 is a semester-1 course: not offered in semester 2
    assert rows("SELECT course_id, semester_id FROM course_registration ORDER BY registration_id") == [(2, 1), (2, 2)]


def test_cancelled_registration_blocks_reregistering_with_clear_note(sam, client):
    sam.register(1)
    _exec("UPDATE course_registration SET registration_status='CANCELLED'")
    html = sam.get("/student/available-courses").get_data(as_text=True)
    assert "cancelled registration exists" in html
    sam.register(1)
    assert one("SELECT COUNT(*) FROM course_registration") == 1


def test_new_semester_offers_new_courses(sam):
    advance(1, 2)
    html = sam.get("/student/available-courses").get_data(as_text=True)
    assert set(codes(html, "Courses offered this semester")) == {"CS201"}


# --------------------------------------------------- registered / marks / results
def test_my_registrations_lists_all_attempts_with_labels(sam):
    sam.register(1); make_result(1, 10, 40, "FAIL")
    advance(1, 2); sam.register(1)
    _exec("INSERT INTO course_registration (registration_id, student_id, course_id, semester_id, registration_status) "
          "VALUES (9, 1, 2, 1, 'CANCELLED')")
    html = sam.get("/student/registrations").get_data(as_text=True)
    assert html.count("CS101") == 2 and "CSE1" in html
    assert "Previous" in html and "Current" in html and "Cancelled" in html
    assert "#1" in html and "#2" in html


def test_my_registrations_empty_state(sam):
    assert "not registered for any course" in sam.get("/student/registrations").get_data(as_text=True)


def test_my_marks_shows_marks_and_snapshot_per_attempt(sam):
    sam.register(1); make_result(1, 35.5, 40, "FAIL")
    advance(1, 2); sam.register(1)
    html = sam.get("/student/marks").get_data(as_text=True)
    assert "35.50" in html and "40.00" in html and "Not entered yet" in html
    # historical snapshot stays even if the official mark changes later
    _exec("UPDATE course SET passing_mark=10 WHERE course_id=1")
    html = sam.get("/student/marks").get_data(as_text=True)
    assert "40.00" in html


def test_my_marks_excludes_cancelled_and_empty_state(sam):
    assert "No marks yet" in sam.get("/student/marks").get_data(as_text=True)
    sam.register(1)
    _exec("UPDATE course_registration SET registration_status='CANCELLED'")
    assert "CS101" not in sam.get("/student/marks").get_data(as_text=True)


def test_my_results_latest_attempt_decides(sam):
    sam.register(1); make_result(1, 10, 40, "FAIL")
    advance(1, 2); sam.register(1); make_result(2, 80, 40, "PASS")
    html = sam.get("/student/results").get_data(as_text=True)
    current = html.split("Current result for each course")[1].split("Failed courses open")[0]
    assert "PASS" in current and "FAIL" not in current and "#2" in current
    earlier = html.split("Earlier attempts")[1]
    assert "FAIL" in earlier and "#1" in earlier


def test_my_results_lists_failed_courses_eligible_for_reattempt(sam):
    sam.register(1); make_result(1, 10, 40, "FAIL")
    advance(1, 2)
    html = sam.get("/student/results").get_data(as_text=True)
    seg = html.split("Failed courses open for reattempt")[1].split("Earlier attempts")[0]
    assert "CS101" in seg and "Go to Available Courses" in seg


def test_results_empty_state(sam):
    html = sam.get("/student/results").get_data(as_text=True)
    assert "No results yet" in html and "No failed course is open" in html


# ----------------------------------------------------------- isolation
def test_student_never_sees_another_students_data(client, login, world):
    _exec("""INSERT INTO course_registration (registration_id, student_id, course_id, semester_id, marks_obtained,
             passing_mark_used, result, registration_status) VALUES (1, 2, 1, 1, 77, 40, 'PASS', 'COMPLETED')""")
    login("student", "sam@test.edu")
    for path in ("/student/registrations", "/student/marks", "/student/results", "/student/available-courses"):
        html = client.get(path).get_data(as_text=True)
        assert "77" not in html and "Sue Student" not in html, path
    # Sue's passed course is not blocked for Sam
    assert "CS101" in codes(client.get("/student/available-courses").get_data(as_text=True),
                            "Courses offered this semester")


def test_phase6_pages_are_not_placeholders(sam):
    for p in ("available-courses", "registrations", "marks", "results"):
        assert "not available yet" not in sam.get(f"/student/{p}").get_data(as_text=True)


def test_listed_courses_can_all_be_registered(sam):
    """The list and the enforced rules must agree: every unblocked option registers successfully."""
    _exec("INSERT INTO course VALUES (9,'CS102','Another Core','CORE',1,1,1,NULL)")
    html = sam.get("/student/available-courses").get_data(as_text=True)
    listed = {r[0]: r[1] for r in rows("SELECT course_code, course_id FROM course")}
    for code in codes(html, "Courses offered this semester"):
        if code in ("CSE3",):
            continue
        assert sam.register(listed[code]).status_code == 302
    assert one("SELECT COUNT(*) FROM course_registration") == 4   # CS101, CS102, CSE1, CSE2
