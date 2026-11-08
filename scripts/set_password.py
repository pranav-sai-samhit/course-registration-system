"""Create or reset an account password securely (stores a hash, never plain text).

Examples (run from the project folder, with .env configured):
    python scripts/set_password.py admin  admin@example.edu            # reset
    python scripts/set_password.py admin  new@example.edu --create --name "Site Admin"
    python scripts/set_password.py faculty f.name@example.edu
    python scripts/set_password.py student s.name@example.edu

The password is typed at a hidden prompt, so it never appears in shell history.
Only the admin role can be created here; faculty and students are created by an
admin inside the application (they need program/department details).
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import security                                    # noqa: E402
from database import get_db_connection             # noqa: E402

TABLES = {
    "admin":   ("admin", "admin_id", "password"),
    "faculty": ("faculty", "faculty_id", "password_hash"),
    "student": ("student", "student_id", "password_hash"),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("role", choices=TABLES)
    ap.add_argument("email")
    ap.add_argument("--create", action="store_true", help="create the account (admin only)")
    ap.add_argument("--name", help="display name when creating an admin")
    args = ap.parse_args()

    table, id_col, secret_col = TABLES[args.role]
    email = args.email.strip().lower()

    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    problem = security.check_password_strength(password)
    if problem:
        sys.exit(problem)
    hashed = security.hash_password(password)

    conn = get_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(f"SELECT {id_col} FROM {table} WHERE LOWER(email) = %s", (email,))
            row = cur.fetchone()
            if args.create:
                if args.role != "admin":
                    sys.exit("--create is supported for the admin role only.")
                if row:
                    sys.exit("An admin with that email already exists. Omit --create to reset it.")
                if not args.name:
                    sys.exit("--name is required with --create.")
                cur.execute("LOCK TABLE public.admin IN EXCLUSIVE MODE")
                cur.execute("SELECT COALESCE(MAX(admin_id), 0) + 1 FROM public.admin")
                new_id = cur.fetchone()[0]
                cur.execute("INSERT INTO admin (admin_id, name, email, password) VALUES (%s, %s, %s, %s)",
                            (new_id, args.name.strip(), email, hashed))
                print(f"Admin created (id {new_id}).")
            else:
                if not row:
                    sys.exit(f"No {args.role} account found with that email.")
                cur.execute(f"UPDATE {table} SET {secret_col} = %s WHERE {id_col} = %s", (hashed, row[0]))
                print("Password updated.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
