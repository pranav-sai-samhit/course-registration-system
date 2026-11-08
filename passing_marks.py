"""Official passing-mark changes. Every change is recorded in passing_mark_approval."""
import database as db


class PassingMarkError(ValueError):
    """Safe-to-show message."""


# Row conventions in passing_mark_approval (no schema change needed):
#   faculty proposal, waiting : faculty_id set, faculty_status='APPROVED' (submitted by that faculty
#                               member), admin_status='PENDING', admin_id NULL, approval_date NULL
#   approved / rejected       : admin_status APPROVED/REJECTED, admin_id and approval_date (decision date)
#   admin-initiated change    : faculty_id NULL, admin_id set, both statuses APPROVED


def admin_set_passing_mark(course_id, mark, admin_id):
    """Admin-initiated change (caller commits).

    Updates the official mark and logs the change as an already-approved row with
    faculty_id NULL. faculty_status is 'APPROVED' only because the column is NOT NULL and
    no faculty step applies; rows with faculty_id NULL are admin-initiated.
    """
    if db.execute("UPDATE course SET passing_mark = %s WHERE course_id = %s", (mark, course_id)) == 0:
        raise ValueError("Course not found.")
    approval_id = db.next_id("passing_mark_approval", "approval_id")
    db.execute("""
        INSERT INTO passing_mark_approval
            (approval_id, course_id, proposed_passing_mark, faculty_id, admin_id,
             faculty_status, admin_status, approval_date)
        VALUES (%s, %s, %s, NULL, %s, 'APPROVED', 'APPROVED', CURRENT_DATE)
    """, (approval_id, course_id, mark, admin_id))


def _assigned(faculty_id, course_id):
    return db.query_one("""SELECT 1 AS ok FROM faculty_assignment
                           WHERE faculty_id = %s AND course_id = %s AND student_id IS NULL""",
                        (faculty_id, course_id)) is not None


def faculty_propose(faculty_id, course_id, mark):
    """New proposal for an assigned course (caller commits). One pending proposal per faculty+course."""
    course = db.query_one("SELECT course_id, passing_mark FROM course WHERE course_id = %s FOR SHARE", (course_id,))
    if not course or not _assigned(faculty_id, course_id):
        raise PassingMarkError("You can propose a passing mark only for courses assigned to you.")
    if course["passing_mark"] is not None and course["passing_mark"] == mark:
        raise PassingMarkError("That is already the official passing mark for this course.")
    pending = db.query_one("""SELECT approval_id FROM passing_mark_approval
                              WHERE faculty_id = %s AND course_id = %s AND admin_status = 'PENDING'""",
                           (faculty_id, course_id))
    if pending:
        raise PassingMarkError("You already have a pending proposal for this course. Edit it instead.")
    approval_id = db.next_id("passing_mark_approval", "approval_id")
    db.execute("""
        INSERT INTO passing_mark_approval
            (approval_id, course_id, proposed_passing_mark, faculty_id, admin_id,
             faculty_status, admin_status, approval_date)
        VALUES (%s, %s, %s, %s, NULL, 'APPROVED', 'PENDING', NULL)""", (approval_id, course_id, mark, faculty_id))
    return approval_id


def faculty_edit(faculty_id, approval_id, mark):
    """Change the value of the faculty member's OWN pending proposal (caller commits)."""
    row = db.query_one("""SELECT approval_id, course_id, faculty_id, admin_status FROM passing_mark_approval
                          WHERE approval_id = %s FOR UPDATE""", (approval_id,))
    if not row or row["faculty_id"] != faculty_id:
        raise PassingMarkError("Proposal not found.")
    if row["admin_status"] != "PENDING":
        raise PassingMarkError("This proposal has already been decided and can no longer be edited.")
    current = db.query_one("SELECT passing_mark FROM course WHERE course_id = %s", (row["course_id"],))["passing_mark"]
    if current is not None and current == mark:
        raise PassingMarkError("That is already the official passing mark for this course.")
    db.execute("UPDATE passing_mark_approval SET proposed_passing_mark = %s WHERE approval_id = %s",
               (mark, approval_id))


def admin_decide(approval_id, admin_id, approve):
    """Approve or reject a pending proposal (caller commits). Approving updates the official mark."""
    row = db.query_one("""SELECT approval_id, course_id, proposed_passing_mark, admin_status
                          FROM passing_mark_approval WHERE approval_id = %s FOR UPDATE""", (approval_id,))
    if not row:
        raise PassingMarkError("Proposal not found.")
    if row["admin_status"] != "PENDING":
        raise PassingMarkError("This proposal has already been decided.")
    if approve:
        db.execute("UPDATE course SET passing_mark = %s WHERE course_id = %s",
                   (row["proposed_passing_mark"], row["course_id"]))
    db.execute("""UPDATE passing_mark_approval SET admin_status = %s, admin_id = %s, approval_date = CURRENT_DATE
                  WHERE approval_id = %s""", ("APPROVED" if approve else "REJECTED", admin_id, approval_id))
    return row


def history(faculty_id=None):
    """All approval rows, newest first; optionally only one faculty member's."""
    where, params = ("WHERE pa.faculty_id = %s", (faculty_id,)) if faculty_id else ("", ())
    return db.query_all(f"""
        SELECT pa.approval_id, pa.course_id, c.course_code, c.course_name, c.passing_mark AS official_mark,
               pa.proposed_passing_mark, pa.faculty_id, f.name AS faculty_name, pa.admin_id, a.name AS admin_name,
               pa.faculty_status, pa.admin_status, pa.approval_date
        FROM passing_mark_approval pa JOIN course c ON c.course_id = pa.course_id
        LEFT JOIN faculty f ON f.faculty_id = pa.faculty_id LEFT JOIN admin a ON a.admin_id = pa.admin_id
        {where} ORDER BY pa.approval_id DESC""", params)
