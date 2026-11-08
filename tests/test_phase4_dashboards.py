"""Phase 4: navigation-only dashboards and one working page per navigation item."""
import re

import pytest

import navigation
from conftest import _exec

ACCOUNTS = {"admin": "admin@test.edu", "faculty": "fay@test.edu", "student": "sam@test.edu"}

EXPECTED = {
    "admin": [
        ("Academic Management", ["Students", "Faculty", "Programs", "Departments", "Semesters", "Courses"]),
        ("Registration & Administration", ["Course Registrations", "Faculty Assignments", "Passing Mark Approvals"]),
    ],
    "faculty": [(None, ["My Assigned Courses", "My Assigned Students", "Marks Entry",
                        "Student Results", "Passing Mark Requests"])],
    "student": [(None, ["My Profile", "Available Courses", "My Registered Courses", "My Marks", "My Results"])],
}


def links(html):
    return re.findall(r'<a [^>]*href="([^"]*)"', html)


def main_html(html):
    """Page content between the navbar and the footer."""
    return html[html.index("<main"):html.index("</main>")]


# ------------------------------------------------- registry matches the spec
@pytest.mark.parametrize("role", EXPECTED)
def test_registry_matches_specification(role):
    got = [(g["title"], [i["title"] for i in g["items"]]) for g in navigation.NAV[role]]
    assert got == EXPECTED[role]


def test_every_registry_item_has_a_registered_route(app):
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    for role in ACCOUNTS:
        assert f"{role}.dashboard" in endpoints
        for item in navigation.items(role):
            assert f"{role}.{item['key']}" in endpoints, item


def test_route_paths_are_unique_per_role(app):
    rules = [r.rule for r in app.url_map.iter_rules() if r.endpoint.split(".")[0] in ACCOUNTS]
    assert len(rules) == len(set(rules))


# ---------------------------------------------------------- dashboards
@pytest.mark.parametrize("role,email", ACCOUNTS.items())
def test_dashboard_has_exactly_the_specified_links_in_order(client, login, app, role, email):
    login(role, email)
    html = main_html(client.get(f"/{role}/dashboard").get_data(as_text=True))
    with app.test_request_context():
        from flask import url_for
        expected_hrefs = [url_for(f"{role}.{i['key']}") for i in navigation.items(role)]
    assert [h for h in links(html)] == expected_hrefs
    # titles appear in the specified order
    titles = [t for _, ts in EXPECTED[role] for t in ts]
    positions = [html.index(t) for t in titles]
    assert positions == sorted(positions)


def test_admin_dashboard_has_two_group_headings(client, login):
    login("admin", "admin@test.edu")
    html = client.get("/admin/dashboard").get_data(as_text=True)
    assert html.count("Academic Management") == 1 and html.count("Registration &amp; Administration") == 1
    assert html.index("Academic Management") < html.index("Registration &amp; Administration")


@pytest.mark.parametrize("role,email", ACCOUNTS.items())
def test_dashboards_are_navigation_only(client, login, role, email):
    login(role, email)
    html = main_html(client.get(f"/{role}/dashboard").get_data(as_text=True))
    for forbidden in ("<table", "<canvas", "<svg", "<form", "<input", "<button", "badge", "progress"):
        assert forbidden not in html, forbidden
    visible_text = re.sub(r"<[^>]+>", " ", html)          # tags/classes/hrefs removed
    assert not re.search(r"\d", visible_text), f"dashboard shows numbers: {visible_text.split()}"


def test_dashboard_does_not_query_data_tables(app, client, login, monkeypatch):
    """Dashboards must not touch course/registration data (only login does)."""
    import database
    login("admin", "admin@test.edu")
    calls = []
    original = database.query_all
    monkeypatch.setattr(database, "query_all", lambda *a, **k: calls.append(a) or original(*a, **k))
    monkeypatch.setattr(database, "query_one", lambda *a, **k: calls.append(a))
    for role in ACCOUNTS:
        client.get(f"/{role}/dashboard")
    assert calls == []


# ----------------------------------------------------- every page works
@pytest.mark.parametrize("role,email", ACCOUNTS.items())
def test_every_nav_page_opens_with_title_sidebar_and_breadcrumb(client, login, app, role, email):
    login(role, email)
    for item in navigation.items(role):
        with app.test_request_context():
            from flask import url_for
            url = url_for(f"{role}.{item['key']}")
        r = client.get(url)
        assert r.status_code == 200, url
        html = r.get_data(as_text=True)
        assert f'<h1 class="h3 mb-1">{item["title"].replace("&", "&amp;")}</h1>' in html, url
        assert 'aria-current="page"' in html
        assert "breadcrumb" in html
        # sidebar lists every item of this role, and only this item is active
        for other in navigation.items(role):
            assert other["title"].replace("&", "&amp;") in html
        assert html.count("list-group-item list-group-item-action active") == 1


@pytest.mark.parametrize("role,email", ACCOUNTS.items())
def test_no_dead_links_on_any_page(client, login, app, role, email):
    login(role, email)
    pages = [f"/{role}/dashboard"]
    with app.test_request_context():
        from flask import url_for
        pages += [url_for(f"{role}.{i['key']}") for i in navigation.items(role)]
    seen = set()
    for page in pages:
        for href in links(client.get(page).get_data(as_text=True)):
            assert href not in ("#", "", "javascript:void(0)"), (page, href)
            if href.startswith("/") and href not in seen:
                seen.add(href)
                assert client.get(href).status_code in (200, 302), (page, href)


# --------------------------------------------------- access restrictions
def test_all_nav_pages_block_other_roles_and_anonymous(client, login, app):
    all_paths = {}
    with app.test_request_context():
        from flask import url_for
        for role in ACCOUNTS:
            all_paths[role] = [url_for(f"{role}.{i['key']}") for i in navigation.items(role)]
    for role, paths in all_paths.items():           # anonymous
        for p in paths:
            r = client.get(p)
            assert r.status_code == 302 and r.headers["Location"].endswith(f"/{role}/login"), p
    for role, email in ACCOUNTS.items():            # each role vs the others' pages
        login(role, email)
        for other, paths in all_paths.items():
            for p in paths:
                assert client.get(p).status_code == (200 if other == role else 403), (role, p)
        client.post("/logout", data={"csrf_token": __import__("conftest").get_csrf(client, f"/{role}/dashboard")})


# ------------------------------------------------------ student profile
def test_student_profile_shows_own_record_only(client, login):
    _exec("UPDATE student SET current_semester_id=3 WHERE student_id=1")
    login("student", "sam@test.edu")
    html = client.get("/student/profile").get_data(as_text=True)
    for expected in ("Sam Student", "sam@test.edu", "B.Tech", "CSE", "Semester 3", "Year 2"):
        assert expected in html
    assert "Sue Student" not in html and "sue@test.edu" not in html


def test_student_profile_follows_session_not_url(client, login):
    login("student", "sue@test.edu")
    assert "Sue Student" in client.get("/student/profile").get_data(as_text=True)
    # no ID parameter exists that could expose another student
    assert client.get("/student/profile/1").status_code == 404
    assert "Sam Student" not in client.get("/student/profile?student_id=1").get_data(as_text=True)


def test_no_navigation_page_is_a_placeholder_any_more(app):
    assert all(i["phase"] is None for r in ACCOUNTS for i in navigation.items(r))
