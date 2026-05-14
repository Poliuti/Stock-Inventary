import os
import json
from datetime import datetime
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MOVEMENTS_FILE = os.path.join(DATA_DIR, "movements.json")


def load_movements():
    if not os.path.exists(MOVEMENTS_FILE):
        return []
    with open(MOVEMENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_movement(ref, location, designation, mov_type, quantity, notes=""):
    movements = load_movements()
    entry = {
        "id": len(movements) + 1,
        "ref": ref,
        "location": location,
        "designation": designation,
        "type": mov_type,
        "quantity": int(quantity),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "notes": notes,
    }
    movements.append(entry)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MOVEMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(movements, f, ensure_ascii=False, indent=2)
    return entry


def _get_adjustments():
    adjustments = {}
    for m in load_movements():
        key = f"{m['location']}_{m['ref']}"
        delta = m["quantity"] if m["type"] == "entrée" else -m["quantity"]
        adjustments[key] = adjustments.get(key, 0) + delta
    return adjustments


def _clean_str(val):
    if pd.isna(val):
        return ""
    return str(val).strip()


def _clean_num(val):
    if pd.isna(val):
        return None
    try:
        f = float(val)
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return None


def load_rex():
    path = os.path.join(DATA_DIR, "Rex.xlsx")
    df = pd.read_excel(path, sheet_name="Inventaire 2026")
    items = []
    for _, row in df.iterrows():
        designation = _clean_str(row.get("Désignation", ""))
        if not designation:
            continue
        qty = _clean_num(row.get("Quantite"))
        current = _clean_num(row.get("STOCK\nACTUEL"))
        items.append({
            "ref": _clean_str(row.get("REF", "")),
            "designation": designation,
            "category": _clean_str(row.get("Type", "")),
            "location": "Rex",
            "room": _clean_str(row.get("Chambre", "")),
            "responsible": _clean_str(row.get("Utilisateur/responsable", "")),
            "brand": _clean_str(row.get("Marque", "")),
            "serial": _clean_str(row.get("Num de série ", "")),
            "owner": _clean_str(row.get("Origine ou Propriétaire ", "")),
            "quantity": current if current is not None else qty,
            "min_quantity": None,
            "condition": "",
            "purchase_date": _clean_str(row.get("Date d'achat  ou arrivée", "")),
            "cost": _clean_num(row.get("Cout\n(VAT incl.)")),
            "notes": _clean_str(row.get("REMARQUE", "")),
            "stock_initial": _clean_num(row.get("Stock Initial")),
            "entries": _clean_num(row.get("Entrées Totales")),
            "exits": _clean_num(row.get("Sorties Totales")),
            "current_stock": current,
        })
    return items


def _load_inventaire(filename, sheet, location):
    path = os.path.join(DATA_DIR, filename)
    df = pd.read_excel(path, sheet_name=sheet)

    desig_col = None
    for c in ["DESIGNATION (FR)", "DESIGNATION", "DÉSIGNATION"]:
        if c in df.columns:
            desig_col = c
            break

    items = []
    for _, row in df.iterrows():
        designation = _clean_str(row.get(desig_col, "")) if desig_col else ""
        if not designation:
            continue
        room_val = _clean_str(row.get("CHAMBRE", "") or row.get("EMPLACEMENT", ""))
        items.append({
            "ref": str(int(row["N°"])) if pd.notna(row.get("N°")) else "",
            "designation": designation,
            "designation_it": _clean_str(row.get("DESIGNATION (IT)", "")),
            "category": _clean_str(row.get("CATÉGORIE", "")),
            "location": location,
            "room": room_val,
            "responsible": "",
            "brand": "",
            "serial": "",
            "owner": "",
            "quantity": _clean_num(row.get("N PIECES")),
            "min_quantity": _clean_num(row.get("QUANTITÉ MINIMALE")),
            "condition": _clean_str(row.get("ÉTAT", "")),
            "purchase_date": _clean_str(row.get("DATE_D_ENTRÉE", "")),
            "cost": None,
            "notes": _clean_str(row.get("NOTES", "")),
            "stock_initial": None,
            "entries": None,
            "exits": None,
            "current_stock": _clean_num(row.get("N PIECES")),
        })
    return items


def load_ankofafa():
    return _load_inventaire("Ankofafa.xlsx", "Inventaire_0126", "Ankofafa")


def load_fille():
    return _load_inventaire("Fille.xlsx", "Inventaire_0126", "Fille")


def load_all_inventory():
    adjustments = _get_adjustments()
    items = []
    for i, loader in enumerate([load_rex, load_ankofafa, load_fille]):
        for item in loader():
            item["id"] = f"{i}_{item['ref']}"
            key = f"{item['location']}_{item['ref']}"
            adj = adjustments.get(key, 0)
            if adj:
                base = item["quantity"] or 0
                item["quantity"] = base + adj
                item["current_stock"] = item["quantity"]
            items.append(item)
    return items


def load_alerts():
    alerts = []

    def _parse_alerts(filename, location):
        path = os.path.join(DATA_DIR, filename)
        try:
            df = pd.read_excel(path, sheet_name="Matériel à contrôler")
        except Exception:
            return
        for col in df.columns:
            col_str = str(col)
            if col_str.startswith("Unnamed") or col_str.startswith("Inventaire"):
                continue
            for val in df[col].dropna():
                v = str(val).strip()
                if v and v not in ("NaN", "nan"):
                    alerts.append({
                        "location": location,
                        "type": col_str,
                        "item": v,
                    })

    _parse_alerts("Ankofafa.xlsx", "Ankofafa")
    _parse_alerts("Fille.xlsx", "Fille")
    return alerts


def load_biblioteca():
    path = os.path.join(DATA_DIR, "Biblioteca.xlsx")
    df = pd.read_excel(path, sheet_name="Lista Libri")
    books = []
    for _, row in df.iterrows():
        code = _clean_str(row.get("Codice Libro", ""))
        title = _clean_str(row.get("Titolo", ""))
        if not title and not code:
            continue
        books.append({
            "code": code,
            "title": title,
            "author": _clean_str(row.get("Autore", "")),
            "category": _clean_str(row.get("Categoria", "")),
            "language": _clean_str(row.get("Lingua", "")),
            "status": _clean_str(row.get("Stato", "")),
            "borrower": _clean_str(row.get("Nome Prestatario", "")),
            "borrower_contact": _clean_str(row.get("Contatto Prestatario", "")),
            "loan_date": _clean_str(row.get("Data Prestito", "")),
            "due_date": _clean_str(row.get("Data Restituzione Prevista (impostato a 30 gg dopo)", "")),
            "notes": _clean_str(row.get("Note", "")),
        })

    try:
        df_loans = pd.read_excel(path, sheet_name="Prestiti Attivi (non modificare")
        loans = []
        for _, row in df_loans.iterrows():
            title = _clean_str(row.get("Titolo", ""))
            if not title:
                continue
            loans.append({
                "code": _clean_str(row.get("Codice Libro", "")),
                "title": title,
                "author": _clean_str(row.get("Autore", "")),
                "borrower": _clean_str(row.get("Nome Prestatario", "")),
                "loan_date": _clean_str(row.get("Data Prestito", "")),
                "due_date": _clean_str(row.get("Data Scadenza", "")),
                "loan_status": _clean_str(row.get("Stato Prestito", "")),
            })
    except Exception:
        loans = []

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
        loc = item["location"]
        cat = item["category"] or "Autre"
        room = item["room"] or "Non spécifié"
        cond = _normalize_condition(item.get("condition") or "")

        by_location[loc] = by_location.get(loc, 0) + 1
        by_category[cat] = by_category.get(cat, 0) + 1
        by_room[room] = by_room.get(room, 0) + 1
        by_condition_all[cond] = by_condition_all.get(cond, 0) + 1

    # Condition chart: only rated items, sorted by severity order
    by_condition_rated = {
        k: by_condition_all[k]
        for k in CONDITION_ORDER
        if k in by_condition_all
    }
    rated_total = sum(by_condition_rated.values())

    top_categories = dict(
        sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:12]
    )
    top_rooms = dict(
        sorted(by_room.items(), key=lambda x: x[1], reverse=True)[:12]
    )

    low_stock = [
        i for i in items
        if i.get("min_quantity") and i.get("quantity") is not None
        and i["quantity"] < i["min_quantity"]
    ]

    movement_by_day = {}
    if movements:
        from datetime import datetime
        for m in movements:
            try:
                d = datetime.strptime(m["date"], "%Y-%m-%d %H:%M")
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
        "condition_rated_total": rated_total,
        "low_stock": low_stock,
        "movement_by_day": movement_by_day,
    }
