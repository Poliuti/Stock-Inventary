import os
import json
from functools import wraps
from flask import redirect, url_for, abort
from flask_login import LoginManager, UserMixin, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")

# Locations accessible per role
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
    def __init__(self, data):
        self.id            = data["username"]
        self.username      = data["username"]
        self.role          = data["role"]
        self.password_hash = data["password_hash"]

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
    if not os.path.exists(USERS_FILE):
        return _create_defaults()
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return {u["username"]: User(u) for u in json.load(f)}


def save_users(users_dict):
    data = [
        {"username": u.username, "role": u.role, "password_hash": u.password_hash}
        for u in users_dict.values()
    ]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _create_defaults():
    defaults = [
        ("admin",      "admin",     "Admin2024!"),
        ("educateur",  "educateur", "Edu2024!"),
        ("logistic",   "logistic",  "Log2024!"),
    ]
    users = {}
    data  = []
    for username, role, pwd in defaults:
        row = {"username": username, "role": role,
               "password_hash": generate_password_hash(pwd)}
        users[username] = User(row)
        data.append(row)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return users


def get_user(user_id):
    return load_users().get(user_id)


def add_user(username, role, password):
    users = load_users()
    if username in users:
        return False, "Nom d'utilisateur déjà existant"
    row = {"username": username, "role": role,
           "password_hash": generate_password_hash(password)}
    users[username] = User(row)
    save_users(users)
    return True, None


def delete_user(username):
    users = load_users()
    if username not in users or users[username].role == "admin":
        return False
    del users[username]
    save_users(users)
    return True


def change_password(username, new_password):
    users = load_users()
    if username not in users:
        return False
    u = users[username]
    row = {"username": u.username, "role": u.role,
           "password_hash": generate_password_hash(new_password)}
    users[username] = User(row)
    save_users(users)
    return True


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
