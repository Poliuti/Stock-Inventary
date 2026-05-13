from flask import Flask, render_template, request, jsonify
from data_loader import (
    load_all_inventory, load_alerts, load_biblioteca, get_stats,
    save_movement, load_movements,
)

app = Flask(__name__)

LOCATION_LABELS = {
    "Rex": "Centre Rex",
    "Ankofafa": "Centre Miaraka Ankofafa",
    "Fille": "Centre Miaraka Fille",
}


@app.route("/")
def dashboard():
    items = load_all_inventory()
    movements = load_movements()
    stats = get_stats(items, movements)
    alerts = load_alerts()
    _, loans = load_biblioteca()
    overdue = [l for l in loans if l.get("loan_status") == "SCADUTO"]
    return render_template(
        "dashboard.html",
        stats=stats,
        alerts=alerts,
        overdue_loans=overdue,
        location_labels=LOCATION_LABELS,
    )


@app.route("/inventory")
def inventory():
    all_items = load_all_inventory()
    location = request.args.get("location", "")
    category = request.args.get("category", "")
    room = request.args.get("room", "")
    search = request.args.get("q", "").lower()

    items = all_items
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

    categories = sorted({i["category"] for i in all_items if i["category"]})
    locations = sorted({i["location"] for i in all_items})
    pool = [i for i in all_items if not location or i["location"] == location]
    rooms = sorted({i["room"] for i in pool if i["room"]})

    return render_template(
        "inventory.html",
        items=items,
        categories=categories,
        locations=locations,
        rooms=rooms,
        location_labels=LOCATION_LABELS,
        selected_location=location,
        selected_category=category,
        selected_room=room,
        search=search,
    )


@app.route("/api/movement", methods=["POST"])
def api_movement():
    data = request.get_json()
    required = {"ref", "location", "designation", "type", "quantity"}
    if not required.issubset(data or {}):
        return jsonify({"error": "missing fields"}), 400
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


@app.route("/mouvements")
def mouvements():
    location = request.args.get("location", "")
    movements = load_movements()
    if location:
        movements = [m for m in movements if m["location"] == location]
    movements = list(reversed(movements))
    return render_template(
        "movements.html",
        movements=movements,
        location_labels=LOCATION_LABELS,
        selected_location=location,
    )


@app.route("/library")
def library():
    books, loans = load_biblioteca()
    return render_template("library.html", books=books, loans=loans)


@app.route("/api/inventory")
def api_inventory():
    items = load_all_inventory()
    return jsonify(items)


if __name__ == "__main__":
    app.run(debug=True)
