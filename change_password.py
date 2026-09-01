"""Change an existing user's password.

Usage:
    python change_password.py                  # prompts for username + password
    python change_password.py justin           # prompts for the password only
    python change_password.py --user justin --pass s3cret   # non-interactive

Prefer an interactive form on a server. The password is read through getpass,
so it never lands in shell history, a process listing, or a terminal log. The
--pass flag exists for scripting and leaks the value into all three.

Note that changing a password does not sign anyone out. Flask-Login sessions
are signed with FLASK_SECRET_KEY and carry only a user id, so an existing
cookie stays valid. To invalidate every live session, rotate that secret too;
see docs/deployment.md.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from werkzeug.security import generate_password_hash

import auth
import db

# Higher than seed.py's floor because this deployment is reachable from the
# public internet, where the login page is the only thing standing in front of
# the content.
MIN_LENGTH = 12


def set_password(username: str, password: str) -> None:
    user = auth.User.by_username(username)
    if user is None:
        print(f"  ! no user named {username!r}", file=sys.stderr)
        sys.exit(1)
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(password), user.id),
    )
    print(f"  password updated for {username!r} (id={user.id})")


def main():
    parser = argparse.ArgumentParser(description="Change a Graphion user's password.")
    parser.add_argument(
        "username", nargs="?", default=None,
        help="Account to update; prompted for if omitted",
    )
    parser.add_argument(
        "--user", dest="user_flag", default=None,
        help="Alias for the positional username",
    )
    parser.add_argument(
        "--pass", dest="password", default=None,
        help="New password; prompted for if omitted (avoid on a shared shell)",
    )
    args = parser.parse_args()

    db.init_db()

    username = args.username or args.user_flag
    if not username:
        username = input("  Username: ").strip()
    if not username:
        print("  ! username required", file=sys.stderr)
        sys.exit(1)

    if args.password:
        password = args.password
    else:
        password = getpass.getpass("  New password: ")
        confirm = getpass.getpass("  Confirm password: ")
        if password != confirm:
            print("  ! passwords do not match", file=sys.stderr)
            sys.exit(1)

    if len(password) < MIN_LENGTH:
        print(
            f"  ! password must be at least {MIN_LENGTH} characters",
            file=sys.stderr,
        )
        sys.exit(1)

    set_password(username, password)
    print("\nDone. Existing sessions stay signed in until their cookie expires;")
    print("rotate FLASK_SECRET_KEY as well to invalidate them.")


if __name__ == "__main__":
    main()
