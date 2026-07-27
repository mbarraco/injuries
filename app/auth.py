"""Application credentials, read from the environment.

Kept out of main.py so the credential rules are testable on their own, and so
there is exactly one place where "is this request allowed" is decided.
"""
import os
import secrets

from dotenv import load_dotenv

# The repo already keeps secrets in a gitignored .env for the ingest scripts;
# the app reads its credentials the same way rather than inventing a second
# mechanism. Existing environment variables win over the file.
load_dotenv()

USER_VAR, PASSWORD_VAR = "INJURY_APP_USER", "INJURY_APP_PASSWORD"


def _configured():
    """The expected credentials, or a loud failure.

    Fails closed. A plain os.getenv default would turn "operator forgot to set
    the password" into "every request authenticates", which is the worst
    possible outcome and a silent one.
    """
    user, password = os.getenv(USER_VAR), os.getenv(PASSWORD_VAR)
    if not user or not password:
        raise RuntimeError(
            f"{USER_VAR} and {PASSWORD_VAR} must be set — "
            f"refusing to serve requests unauthenticated")
    return user, password


def verify(username, password):
    """Whether the supplied credentials match, compared in constant time.

    `secrets.compare_digest` rather than `==` so response timing doesn't reveal
    how many leading characters were correct. The two comparisons are combined
    with `&` (not `and`) deliberately: `and` short-circuits, which would skip
    the password check entirely when the username is wrong and leak that fact
    through timing.
    """
    expected_user, expected_password = _configured()
    return bool(
        secrets.compare_digest(username.encode(), expected_user.encode())
        & secrets.compare_digest(password.encode(), expected_password.encode())
    )
