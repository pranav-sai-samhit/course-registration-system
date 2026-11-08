"""Single source of truth for every dashboard link and sidebar entry.

Each item: key (endpoint name inside its blueprint), path, title, description and
``phase`` - the build phase that fills the page in (None = page already complete).
Dashboards, sidebars, breadcrumbs and tests all read this registry, so a link can
never exist without a route behind it.
"""

NAV = {
    "admin": [
        {"title": "Academic Management", "items": [
            {"key": "students", "path": "/students", "title": "Students",
             "description": "Add and manage student accounts.", "phase": None},
            {"key": "faculty", "path": "/faculty", "title": "Faculty",
             "description": "Add and manage faculty accounts.", "phase": None},
            {"key": "programs", "path": "/programs", "title": "Programs",
             "description": "B.Tech, PhD and other programs.", "phase": None},
            {"key": "departments", "path": "/departments", "title": "Departments",
             "description": "Departments within each program.", "phase": None},
            {"key": "semesters", "path": "/semesters", "title": "Semesters",
             "description": "Semesters and academic years.", "phase": None},
            {"key": "courses", "path": "/courses", "title": "Courses",
             "description": "Courses and official passing marks.", "phase": None},
        ]},
        {"title": "Registration & Administration", "items": [
            {"key": "registrations", "path": "/registrations", "title": "Course Registrations",
             "description": "View and manage all registrations.", "phase": None},
            {"key": "faculty_assignments", "path": "/faculty-assignments", "title": "Faculty Assignments",
             "description": "Course-level and student-level assignment.", "phase": None},
            {"key": "passing_mark_approvals", "path": "/passing-mark-approvals", "title": "Passing Mark Approvals",
             "description": "Review proposals and set passing marks.", "phase": None},
        ]},
    ],
    "faculty": [
        {"title": None, "items": [
            {"key": "my_courses", "path": "/courses", "title": "My Assigned Courses",
             "description": "Courses assigned to you.", "phase": None},
            {"key": "my_students", "path": "/students", "title": "My Assigned Students",
             "description": "Students assigned to you.", "phase": None},
            {"key": "marks_entry", "path": "/marks", "title": "Marks Entry",
             "description": "Enter marks for assigned registrations.", "phase": None},
            {"key": "student_results", "path": "/results", "title": "Student Results",
             "description": "Marks and results of assigned students.", "phase": None},
            {"key": "passing_mark_requests", "path": "/passing-mark-requests", "title": "Passing Mark Requests",
             "description": "Propose and track passing marks.", "phase": None},
        ]},
    ],
    "student": [
        {"title": None, "items": [
            {"key": "profile", "path": "/profile", "title": "My Profile",
             "description": "Your academic details.", "phase": None},
            {"key": "available_courses", "path": "/available-courses", "title": "Available Courses",
             "description": "Courses you can register for.", "phase": None},
            {"key": "my_registrations", "path": "/registrations", "title": "My Registered Courses",
             "description": "All your registration attempts.", "phase": None},
            {"key": "my_marks", "path": "/marks", "title": "My Marks",
             "description": "Marks for each attempt.", "phase": None},
            {"key": "my_results", "path": "/results", "title": "My Results",
             "description": "Current results and reattempts.", "phase": None},
        ]},
    ],
}


def items(role):
    return [item for group in NAV[role] for item in group["items"]]


def find(role, key):
    return next(i for i in items(role) if i["key"] == key)
