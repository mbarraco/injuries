"""Application credentials, read from the environment.

Kept out of main.py so the credential rules are testable on their own, and so
there is exactly one place where "is this request allowed" is decided.
"""
import os
import secrets

from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

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


# One shared HTTPBasic dependency for every router. Both main.py and af_routes.py
# used to define their own copy of this pair — af_routes.py's duplicate existed
# specifically because importing verify_auth from main.py would have been
# circular (main.py imports af_routes to mount it). Splitting Sportmonks into
# its own sportmonks_routes.py made that duplication pointless in every
# direction, so it lives here instead, where nothing needs to import back.
security = HTTPBasic()


async def verify_auth(credentials: HTTPBasicCredentials = Depends(security)):
    if not verify(credentials.username, credentials.password):
        raise HTTPException(status_code=401, detail="Invalid credentials",
                            headers={"WWW-Authenticate": "Basic"})
    return credentials.username
