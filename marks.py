"""Marks entry and result calculation, shared by faculty and admin.

* A registration is graded against the course's OFFICIAL passing mark at the moment marks are
  entered; that value is stored in ``passing_mark_used`` so later changes to the official mark
  never alter historical results.
* No official passing mark -> marks cannot be saved (``MissingPassingMark``).
* Faculty may enter marks once, for registrations assigned to them. Corrections are an admin
  action and keep the passing mark that was stored with the attempt.
"""
import database as db


class MarksError(ValueError):
    """The marks could not be saved; the message is safe to show."""


class MissingPassingMark(MarksError):
    pass


NO_PASSING_MARK_MESSAGE = (
    "No official passing mark is set for this course, so marks cannot be saved yet. "
    "Propose a passing mark under Passing Mark Requests, or ask the administrator to set it.")


def result_for(marks, passing_mark):
    return "PASS" if marks >= passing_mark else "FAIL"


def faculty_may_grade(faculty_id, registration_id):
    return db.query_one(
        "SELECT 1 AS ok FROM faculty_assignment WHERE faculty_id = %s AND registration_id = %s",
        (faculty_id, registration_id)) is not None


def save_marks(registration_id, marks, faculty_id=None):
    """Save marks (caller commits). ``faculty_id`` set => faculty rules; None => admin rules.

    Returns ``(result, passing_mark_used)``.
    """
    reg = db.query_one("""
        SELECT registration_id, course_id, result, registration_status, passing_mark_used
        FROM course_registration WHERE registration_id = %s FOR UPDATE""", (registration_id,))
    if not reg:
        raise MarksError("Registration not found.")
    if faculty_id is not None and not faculty_may_grade(faculty_id, registration_id):
        raise MarksError("This registration is not assigned to you.")
    if reg["registration_status"] == "CANCELLED":
        raise MarksError("This registration was cancelled; marks cannot be entered.")
    graded = reg["result"] != "PENDING"
    if graded and faculty_id is not None:
        raise MarksError("Marks have already been entered for this attempt. Ask the administrator to correct them.")

    if graded:
        passing = reg["passing_mark_used"]            # a correction keeps the mark that applied to this attempt
    else:
        row = db.query_one("SELECT passing_mark FROM course WHERE course_id = %s FOR SHARE", (reg["course_id"],))
        passing = row["passing_mark"] if row else None
        if passing is None:
            raise MissingPassingMark(NO_PASSING_MARK_MESSAGE)

    result = result_for(marks, passing)
    db.execute("""
        UPDATE course_registration
        SET marks_obtained = %s, passing_mark_used = %s, result = %s, registration_status = 'COMPLETED'
        WHERE registration_id = %s""", (marks, passing, result, registration_id))
    return result, passing
