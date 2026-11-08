"""Phase 8: passing-mark proposals, approval workflow, admin direct change, history."""
import pytest

from conftest import _exec, get_csrf
from test_phase5_admin import admin, flashes, one, rows, world, register, make_result  # noqa: F401
from test_phase7_faculty import course_assign, student_assign, faculty_client, fpost


@pytest.fixture()
def fay(admin, app):
    """Fay teaches CS101 (mark 40) and CSE1 (no mark)."""
    course_assign(admin, faculty=(1,))
    course_assign(admin, faculty=(1,), course_id=2)
    return faculty_client(app)


def propose(c, course, mark):
    return fpost(c, "/faculty/passing-mark-requests/propose", course_id=course, passing_mark=mark)


def decide(admin, approval_id, action):
    return admin.c.post(f"/admin/passing-mark-approvals/{approval_id}/{action}",
                        data={"csrf_token": get_csrf(admin.c, "/admin/dashboard")}, follow_redirects=True)


def approvals():
    return rows("""SELECT approval_id, course_id, proposed_passing_mark, faculty_id, admin_id, faculty_status,
                   admin_status, approval_date IS NOT NULL FROM passing_mark_approval ORDER BY approval_id""")


# ------------------------------------------------------------ faculty side
def test_propose_creates_pending_row_and_official_mark_untouched(fay):
    assert "submitted" in flashes(propose(fay, 1, "55"))
    assert approvals() == [(1, 1, 55, 1, None, "APPROVED", "PENDING", False)]
    assert one("SELECT passing_mark FROM course WHERE course_id=1") == 40


def test_faculty_sees_official_mark_and_own_proposals(fay):
    propose(fay, 2, "50")
    html = fay.get("/faculty/passing-mark-requests").get_data(as_text=True)
    assert "CS101" in html and "official: 40" in html and "official: not set" in html and "Pending" in html


def test_propose_only_for_assigned_courses(fay):
    assert "assigned to you" in flashes(propose(fay, 3, "50"))
    assert approvals() == []


@pytest.mark.parametrize("mark", ["", "x", "-5", "101", "50.555"])
def test_proposal_validation(fay, mark):
    assert flashes(propose(fay, 1, mark))
    assert approvals() == []


def test_proposal_equal_to_official_refused_and_one_pending_per_course(fay):
    assert "already the official" in flashes(propose(fay, 1, "40"))
    propose(fay, 1, "55")
    assert "already have a pending" in flashes(propose(fay, 1, "60"))
    assert len(approvals()) == 1


def test_faculty_edits_own_pending_proposal_only(fay, app, admin):
    propose(fay, 1, "55")
    assert "updated" in flashes(fpost(fay, "/faculty/passing-mark-requests/1/edit", passing_mark="65"))
    assert one("SELECT proposed_passing_mark FROM passing_mark_approval") == 65
    course_assign(admin, faculty=(2,))
    fred = faculty_client(app, "fred@test.edu")
    assert "not found" in flashes(fpost(fred, "/faculty/passing-mark-requests/1/edit", passing_mark="10")).lower()
    assert one("SELECT proposed_passing_mark FROM passing_mark_approval") == 65


def test_decided_proposal_cannot_be_edited(fay, admin):
    propose(fay, 1, "55")
    decide(admin, 1, "reject")
    assert "already been decided" in flashes(fpost(fay, "/faculty/passing-mark-requests/1/edit", passing_mark="70"))
    assert one("SELECT proposed_passing_mark FROM passing_mark_approval") == 55


def test_faculty_cannot_decide_or_set_marks(fay):
    propose(fay, 1, "55")
    t = get_csrf(fay, "/faculty/dashboard")
    assert fay.post("/admin/passing-mark-approvals/1/approve", data={"csrf_token": t}).status_code == 403
    assert fay.post("/admin/passing-mark-approvals/set", data={"csrf_token": t, "course_id": 1,
                                                               "passing_mark": 1}).status_code == 403
    assert one("SELECT passing_mark FROM course WHERE course_id=1") == 40


# -------------------------------------------------------------- admin side
def test_approve_updates_official_mark_and_keeps_history(fay, admin):
    propose(fay, 1, "55")
    assert "updated" in flashes(decide(admin, 1, "approve"))
    assert one("SELECT passing_mark FROM course WHERE course_id=1") == 55
    assert approvals() == [(1, 1, 55, 1, 1, "APPROVED", "APPROVED", True)]


def test_reject_leaves_official_mark_unchanged(fay, admin):
    propose(fay, 1, "55")
    assert "unchanged" in flashes(decide(admin, 1, "reject"))
    assert one("SELECT passing_mark FROM course WHERE course_id=1") == 40
    assert approvals() == [(1, 1, 55, 1, 1, "APPROVED", "REJECTED", True)]


def test_decision_is_final_and_unknown_ids_actions_handled(fay, admin):
    propose(fay, 1, "55")
    decide(admin, 1, "reject")
    assert "already been decided" in flashes(decide(admin, 1, "approve"))
    assert one("SELECT passing_mark FROM course WHERE course_id=1") == 40
    assert "not found" in flashes(decide(admin, 99, "approve")).lower()
    assert "Unknown action" in flashes(decide(admin, 1, "delete"))


def test_approving_a_proposal_for_a_course_with_no_mark_enables_marks_entry(admin, app):
    register(admin, 1, 2, 1)
    course_assign(admin, faculty=(1,), course_id=2)
    student_assign(admin, 1, faculty=(1,), student=1)
    f = faculty_client(app)
    assert "No official passing mark" in flashes(fpost(f, "/faculty/marks/save", registration_id=1, marks="60"))
    propose(f, 2, "45")
    decide(admin, 1, "approve")
    assert "PASS" in flashes(fpost(f, "/faculty/marks/save", registration_id=1, marks="60"))
    assert rows("SELECT passing_mark_used, result FROM course_registration") == [(45, "PASS")]


def test_admin_direct_change_is_logged_and_history_stays(admin):
    t = lambda: get_csrf(admin.c, "/admin/dashboard")
    r = admin.c.post("/admin/passing-mark-approvals/set",
                     data={"csrf_token": t(), "course_id": 2, "passing_mark": "35"}, follow_redirects=True)
    assert "recorded" in flashes(r)
    assert one("SELECT passing_mark FROM course WHERE course_id=2") == 35
    assert approvals() == [(1, 2, 35, None, 1, "APPROVED", "APPROVED", True)]
    admin.c.post("/admin/passing-mark-approvals/set", data={"csrf_token": t(), "course_id": 2, "passing_mark": "50"})
    assert len(approvals()) == 2 and one("SELECT passing_mark FROM course WHERE course_id=2") == 50


@pytest.mark.parametrize("data,msg", [
    ({"course_id": "", "passing_mark": "50"}, "Select a course"),
    ({"course_id": "99", "passing_mark": "50"}, "valid course"),
    ({"course_id": "1", "passing_mark": "150"}, "between 0 and 100"),
    ({"course_id": "1", "passing_mark": ""}, "required"),
    ({"course_id": "1", "passing_mark": "40"}, "already the official"),
])
def test_admin_direct_change_validation(admin, data, msg):
    r = admin.c.post("/admin/passing-mark-approvals/set",
                     data={"csrf_token": get_csrf(admin.c, "/admin/dashboard"), **data})
    assert r.status_code == 400 and msg.lower() in r.get_data(as_text=True).lower()
    assert approvals() == [] and one("SELECT passing_mark FROM course WHERE course_id=1") == 40


def test_admin_page_shows_pending_and_history(fay, admin):
    propose(fay, 1, "55")
    html = admin.get("/admin/passing-mark-approvals").get_data(as_text=True)
    assert "Fay Faculty" in html and "Approve" in html and "Reject" in html
    decide(admin, 1, "approve")
    admin.c.post("/admin/passing-mark-approvals/set",
                 data={"csrf_token": get_csrf(admin.c, "/admin/dashboard"), "course_id": 2, "passing_mark": "30"})
    html = admin.get("/admin/passing-mark-approvals").get_data(as_text=True)
    assert "No proposals are waiting" in html and "Set by admin" in html and "Proposed by Fay Faculty" in html


def test_history_of_results_is_not_rewritten_by_mark_changes(admin, fay, app):
    register(admin, 1, 1, 1)
    student_assign(admin, 1, faculty=(1,), student=1)
    fpost(fay, "/faculty/marks/save", registration_id=1, marks="45")          # PASS against 40
    propose(fay, 1, "80")
    decide(admin, 1, "approve")
    assert rows("SELECT marks_obtained, passing_mark_used, result FROM course_registration") == [(45, 40, "PASS")]


def test_empty_states(admin, fay):
    assert "No proposals are waiting" in admin.get("/admin/passing-mark-approvals").get_data(as_text=True)
    assert "not proposed any" in fay.get("/faculty/passing-mark-requests").get_data(as_text=True)


def test_admin_approval_routes_need_csrf(fay, admin):
    propose(fay, 1, "55")
    assert admin.c.post("/admin/passing-mark-approvals/1/approve").status_code == 400
    assert approvals()[0][6] == "PENDING"
