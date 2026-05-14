from functools import wraps
from flask import abort
from flask_login import LoginManager, UserMixin, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from db import get_db

ROLE_LOCATIONS = {
    "admin":      ["Rex", "Ankofafa", "Fille"],
    "educateur":  ["Ankofafa", "Fille"],
    "logistic":   ["Rex"],
}

ROLE_LABELS = {
    "admin":     "Administrateur",
    "educateur": "Éducateur",
    "logistic":  "Logistique",
}


class User(UserMixin):
    def __init__(self, username, role, password_hash):
        self.id            = username
        self.username      = username
        self.role          = role
        self.password_hash = password_hash

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def locations(self):
        return ROLE_LOCATIONS.get(self.role, [])

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def can_access_library(self):
        return self.role in ("admin", "educateur")

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)


# ── Persistence ───────────────────────────────────────────

def load_users():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT username, role, password_hash FROM users ORDER BY username")
            rows = cur.fetchall()
    return {r["username"]: User(r["username"], r["role"], r["password_hash"]) for r in rows}


def get_user(username):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, role, password_hash FROM users WHERE username = %s",
                (username,)
            )
            row = cur.fetchone()
    if not row:
        return None
    return User(row["username"], row["role"], row["password_hash"])


def add_user(username, role, password):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, role, password_hash) VALUES (%s, %s, %s)",
                    (username, role, generate_password_hash(password))
                )
        return True, None
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return False, "Nom d'utilisateur déjà existant"
        return False, str(e)


def delete_user(username):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            if not row or row["role"] == "admin":
                return False
            cur.execute("DELETE FROM users WHERE username = %s", (username,))
    return True


def change_password(username, new_password):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE username = %s",
                (generate_password_hash(new_password), username)
            )
            updated = cur.rowcount
    return updated > 0


# ── Flask-Login setup ─────────────────────────────────────

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    return get_user(user_id)


# ── Access decorator ──────────────────────────────────────

def requires_role(*roles):
    def decorator(f):
        @wraps(f)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator
