import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from auth import (
    login_manager, load_users, add_user, delete_user, change_password,
    requires_role, ROLE_LABELS, ROLE_LOCATIONS,
)
from data_loader import (
    load_all_inventory, load_alerts, load_biblioteca, get_stats,
    save_movement, load_movements,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "lvpt-stock-secret-2024")
login_manager.init_app(app)

LOCATION_LABELS = {
    "Rex":      "Centre Rex",
    "Ankofafa": "Centre Miaraka Ankofafa",
    "Fille":    "Centre Miaraka Fille",
}


# ── Auth ──────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users = load_users()
        user = users.get(username)
        if user and user.check_password(password):
            login_user(user, remember=True)
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Identifiants incorrects.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── Dashboard ─────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    all_items = load_all_inventory()
    items = [i for i in all_items if i["location"] in current_user.locations]
    movements = [m for m in load_movements() if m["location"] in current_user.locations]
    stats = get_stats(items, movements)
    alerts = [a for a in load_alerts() if a["location"] in current_user.locations]
    overdue = []
    if current_user.can_access_library:
        _, loans = load_biblioteca()
        overdue = [l for l in loans if l.get("loan_status") == "SCADUTO"]
    return render_template(
        "dashboard.html",
        stats=stats, alerts=alerts, overdue_loans=overdue,
        location_labels=LOCATION_LABELS,
    )


# ── Inventory ─────────────────────────────────────────────

@app.route("/inventory")
@login_required
def inventory():
    all_items = load_all_inventory()
    accessible = [i for i in all_items if i["location"] in current_user.locations]

    location = request.args.get("location", "")
    category = request.args.get("category", "")
    room     = request.args.get("room", "")
    search   = request.args.get("q", "").lower()

    # Enforce role boundary: ignore location param if not accessible
    if location and location not in current_user.locations:
        location = ""

    items = accessible
    if location:
        items = [i for i in items if i["location"] == location]
    if category:
        items = [i for i in items if i["category"] == category]
    if room:
        items = [i for i in items if i["room"] == room]
    if search:
        items = [
            i for i in items
            if search in i["designation"].lower()
            or search in i["ref"].lower()
            or search in i["room"].lower()
        ]

    categories = sorted({i["category"] for i in accessible if i["category"]})
    locations  = sorted({i["location"] for i in accessible})
    pool = [i for i in accessible if not location or i["location"] == location]
    rooms = sorted({i["room"] for i in pool if i["room"]})

    return render_template(
        "inventory.html",
        items=items, categories=categories, locations=locations, rooms=rooms,
        location_labels=LOCATION_LABELS,
        selected_location=location, selected_category=category,
        selected_room=room, search=search,
    )


# ── Movements ─────────────────────────────────────────────

@app.route("/mouvements")
@login_required
def mouvements():
    location  = request.args.get("location", "")
    if location and location not in current_user.locations:
        location = ""
    movements = [m for m in load_movements() if m["location"] in current_user.locations]
    if location:
        movements = [m for m in movements if m["location"] == location]
    return render_template(
        "movements.html",
        movements=list(reversed(movements)),
        location_labels={k: v for k, v in LOCATION_LABELS.items()
                         if k in current_user.locations},
        selected_location=location,
    )


@app.route("/api/movement", methods=["POST"])
@login_required
def api_movement():
    data = request.get_json()
    required = {"ref", "location", "designation", "type", "quantity"}
    if not required.issubset(data or {}):
        return jsonify({"error": "missing fields"}), 400
    if data["location"] not in current_user.locations:
        return jsonify({"error": "access denied"}), 403
    if data["type"] not in ("entrée", "sortie"):
        return jsonify({"error": "type must be entrée or sortie"}), 400
    try:
        qty = int(data["quantity"])
        if qty <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "quantity must be a positive integer"}), 400
    entry = save_movement(
        data["ref"], data["location"], data["designation"],
        data["type"], qty, data.get("notes", "")
    )
    return jsonify(entry), 201


# ── Library ───────────────────────────────────────────────

@app.route("/library")
@login_required
def library():
    if not current_user.can_access_library:
        return redirect(url_for("dashboard"))
    books, loans = load_biblioteca()
    return render_template("library.html", books=books, loans=loans)


# ── Admin: user management ────────────────────────────────

@app.route("/admin/users")
@requires_role("admin")
def admin_users():
    users = load_users()
    return render_template(
        "admin_users.html",
        users=users, role_labels=ROLE_LABELS, location_labels=LOCATION_LABELS,
        role_locations=ROLE_LOCATIONS,
    )


@app.route("/admin/users/add", methods=["POST"])
@requires_role("admin")
def admin_add_user():
    username = request.form.get("username", "").strip()
    role     = request.form.get("role", "")
    password = request.form.get("password", "")
    if not username or not role or not password:
        flash("Tous les champs sont requis.", "danger")
    elif role not in ROLE_LABELS:
        flash("Rôle invalide.", "danger")
    else:
        ok, err = add_user(username, role, password)
        flash(f"Utilisateur « {username} » créé." if ok else err,
              "success" if ok else "danger")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/delete/<username>", methods=["POST"])
@requires_role("admin")
def admin_delete_user(username):
    if username == current_user.username:
        flash("Impossible de supprimer votre propre compte.", "danger")
    elif delete_user(username):
        flash(f"Utilisateur « {username} » supprimé.", "success")
    else:
        flash("Suppression impossible (compte admin ou introuvable).", "danger")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/password/<username>", methods=["POST"])
@requires_role("admin")
def admin_change_password(username):
    new_pwd = request.form.get("new_password", "")
    if len(new_pwd) < 6:
        flash("Le mot de passe doit faire au moins 6 caractères.", "danger")
    elif change_password(username, new_pwd):
        flash(f"Mot de passe de « {username} » modifié.", "success")
    else:
        flash("Utilisateur introuvable.", "danger")
    return redirect(url_for("admin_users"))


# ── Error pages ───────────────────────────────────────────

@app.errorhandler(403)
def forbidden(_):
    return render_template("403.html"), 403


if __name__ == "__main__":
    app.run(debug=True)
