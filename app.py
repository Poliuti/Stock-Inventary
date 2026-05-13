from flask import Flask, render_template, request, jsonify
from data_loader import (
    load_all_inventory, load_alerts, load_biblioteca, get_stats
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
    stats = get_stats(items)
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
    items = load_all_inventory()
    location = request.args.get("location", "")
    category = request.args.get("category", "")
    search = request.args.get("q", "").lower()

    if location:
        items = [i for i in items if i["location"] == location]
    if category:
        items = [i for i in items if i["category"] == category]
    if search:
        items = [
            i for i in items
            if search in i["designation"].lower()
            or search in i["ref"].lower()
            or search in i["room"].lower()
        ]

    all_items = load_all_inventory()
    categories = sorted({i["category"] for i in all_items if i["category"]})
    locations = sorted({i["location"] for i in all_items})

    return render_template(
        "inventory.html",
        items=items,
        categories=categories,
        locations=locations,
        location_labels=LOCATION_LABELS,
        selected_location=location,
        selected_category=category,
        search=search,
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
