
"""One-time account creation from environment variables or interactive input."""
import os
from getpass import getpass

from backend.auth import create_user, password_problems
from backend.database import connect, init_db


def main():
    init_db()

    with connect() as db:
        for name in ("controller", "supervisor"):
            if db.execute(
                "SELECT 1 FROM users WHERE username=?", (name,)
            ).fetchone():
                print(f"{name} already exists. Change its password in Security & audit.")
                continue

            env_name = f"SKYCONTROL_{name.upper()}_PASSWORD"
            pwd = os.environ.get(env_name, "").strip()

            if pwd:
                problems = password_problems(pwd)
                if problems:
                    raise SystemExit(
                        f"{env_name} is invalid: " + ", ".join(problems) + "."
                    )
            else:
                while True:
                    pwd = getpass(
                        f"Choose the {name} password "
                        "(12+ characters, letters and digits): "
                    )
                    problems = password_problems(pwd)
                    if problems:
                        print("Password needs " + ", ".join(problems) + ".")
                        continue
                    if pwd != getpass("Confirm password: "):
                        print("Passwords did not match.")
                        continue
                    break

            create_user(
                db, name, pwd, name, f"{name.capitalize()} account", "setup"
            )

    print("Accounts ready. Start SkyControl with: python run.py")


if __name__ == "__main__":
    main()
