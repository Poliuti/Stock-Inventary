from datetime import datetime
from db import get_db


def load_movements():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, ref, location, designation, type, quantity, notes, "
                "to_char(timestamp, 'YYYY-MM-DD HH24:MI') AS date "
                "FROM movements ORDER BY timestamp"
            )
            return [dict(r) for r in cur.fetchall()]


def save_movement(ref, location, designation, mov_type, quantity, notes=""):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO movements (ref, location, designation, type, quantity, notes) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "RETURNING id, ref, location, designation, type, quantity, notes, "
                "to_char(timestamp, 'YYYY-MM-DD HH24:MI') AS date",
                (ref, location, designation, mov_type, int(quantity), notes)
            )
            return dict(cur.fetchone())


def load_all_inventory():
    with get_db() as conn:
        with conn.cursor() as cur:
            # Compute per-item stock adjustments from movements
            cur.execute(
                "SELECT location, ref, "
                "SUM(CASE WHEN type='entrée' THEN quantity ELSE -quantity END) AS delta "
                "FROM movements GROUP BY location, ref"
            )
            adjustments = {
                f"{r['location']}_{r['ref']}": r["delta"]
                for r in cur.fetchall()
            }

            cur.execute(
                "SELECT id, ref, designation, designation_it, category, location, "
                "room, responsible, brand, serial, owner, quantity, min_quantity, "
                "condition, purchase_date, cost, notes, stock_initial, entries, exits "
                "FROM inventory ORDER BY location, id"
            )
            items = []
            for row in cur.fetchall():
                item = dict(row)
                key = f"{item['location']}_{item['ref']}"
                adj = adjustments.get(key, 0)
                base = item["quantity"] or 0
                item["quantity"] = base + adj if adj else base
                item["current_stock"] = item["quantity"]
                items.append(item)
    return items


def load_alerts():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT location, type, item FROM alerts ORDER BY location")
            return [dict(r) for r in cur.fetchall()]


def load_biblioteca():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT code, title, author, category, language, status, "
                "borrower, borrower_contact, loan_date, due_date, notes FROM books"
            )
            books = [dict(r) for r in cur.fetchall()]

            cur.execute(
                "SELECT code, title, author, borrower, loan_date, due_date, loan_status "
                "FROM loans ORDER BY loan_date DESC NULLS LAST"
            )
            loans = [dict(r) for r in cur.fetchall()]
    return books, loans


def _normalize_condition(raw):
    if not raw or not raw.strip():
        return "Non renseigné"
    cl = raw.strip().lower()
    if cl in ("bon", "buono", "bonne"):
        return "Bon"
    if "cass" in cl:
        return "Cassé"
    if "repeindre" in cl:
        return "À repeindre"
    if "r" in cl and ("parer" in cl or "parare" in cl):
        return "À réparer"
    if cl.startswith("us"):
        return "Usé"
    return raw.strip()


CONDITION_ORDER = ["Bon", "Usé", "Cassé", "À réparer", "À repeindre"]


def get_stats(items, movements=None):
    by_location = {}
    by_category = {}
    by_room = {}
    by_condition_all = {}

    for item in items:
        loc  = item["location"]
        cat  = item["category"] or "Autre"
        room = item["room"] or "Non spécifié"
        cond = _normalize_condition(item.get("condition") or "")

        by_location[loc]  = by_location.get(loc, 0) + 1
        by_category[cat]  = by_category.get(cat, 0) + 1
        by_room[room]     = by_room.get(room, 0) + 1
        by_condition_all[cond] = by_condition_all.get(cond, 0) + 1

    by_condition_rated = {
        k: by_condition_all[k]
        for k in CONDITION_ORDER
        if k in by_condition_all
    }

    top_categories = dict(sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:12])
    top_rooms      = dict(sorted(by_room.items(),     key=lambda x: x[1], reverse=True)[:12])

    low_stock = [
        i for i in items
        if i.get("min_quantity") and i.get("quantity") is not None
        and i["quantity"] < i["min_quantity"]
    ]

    movement_by_day = {}
    if movements:
        for m in movements:
            try:
                d   = datetime.strptime(m["date"], "%Y-%m-%d %H:%M")
                key = d.strftime("%Y-%m-%d")
                if key not in movement_by_day:
                    movement_by_day[key] = {"entrée": 0, "sortie": 0}
                movement_by_day[key][m["type"]] = (
                    movement_by_day[key].get(m["type"], 0) + m["quantity"]
                )
            except Exception:
                pass

    return {
        "total": len(items),
        "by_location": by_location,
        "by_category": top_categories,
        "by_room": top_rooms,
        "by_condition": by_condition_rated,
        "condition_rated_total": sum(by_condition_rated.values()),
        "low_stock": low_stock,
        "movement_by_day": movement_by_day,
    }
