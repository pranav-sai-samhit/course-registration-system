# Test report
Environment: throwaway PostgreSQL 16 server in the build sandbox, database `CourseRegistrationDB_test`
rebuilt from the DDL in your dump. NOT your real database. The sandbox could not install psycopg2, so the live tests
ran through a small libpq-based stand-in for psycopg2 (test-only, not shipped). The real psycopg2-binary path was not exercised.
Not tested: real browser rendering and the small JavaScript pieces (cascading selects, table filter, confirm dialogs).

Result: 212 passed, 0 failed (live database).
* Phase 3 auth/CSRF/role isolation/DB layer: 39 · Phase 4 dashboards/navigation: 23 · Phase 5 admin CRUD + registration rules (incl. concurrent elective limit): 61
* Phase 6 student pages: 29 · Phase 7 assignments, faculty pages, marks: 34 · Phase 8 approval workflow: 26 (counts approximate)
Static: all Python compiles; app starts; 51 routes registered; every navigation link has a working page.
Mutation checks (tests fail when protections are broken): CSRF, role checks, elective limit, passed-course check, row lock,
passing-mark-required-for-marks, faculty-assignment check on marks, approval-updates-official-mark.
