#!/usr/bin/env python3
"""
One-time migration script.
Reads Excel files from data/ and populates Supabase with all tables + default users.

Usage:
  python migrate.py            # skip tables that already have data
  python migrate.py --force    # truncate inventory/books/loans/alerts and re-import
"""
import os
import sys
import json

import pandas as pd
import psycopg2
import psycopg2.extras
from datetime import datetime
from werkzeug.security import generate_password_hash

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
FORCE    = "--force" in sys.argv

# ── Schema ────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    role          TEXT NOT NULL,
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory (
    id            SERIAL PRIMARY KEY,
    ref           TEXT    DEFAULT '',
    designation   TEXT    NOT NULL,
    designation_it TEXT   DEFAULT '',
    category      TEXT    DEFAULT '',
    location      TEXT    NOT NULL,
    room          TEXT    DEFAULT '',
    responsible   TEXT    DEFAULT '',
    brand         TEXT    DEFAULT '',
    serial        TEXT    DEFAULT '',
    owner         TEXT    DEFAULT '',
    quantity      INTEGER,
    min_quantity  INTEGER,
    condition     TEXT    DEFAULT '',
    purchase_date TEXT    DEFAULT '',
    cost          NUMERIC,
    notes         TEXT    DEFAULT '',
    stock_initial INTEGER,
    entries       INTEGER,
    exits         INTEGER
);

CREATE TABLE IF NOT EXISTS movements (
    id          SERIAL PRIMARY KEY,
    ref         TEXT        DEFAULT '',
    location    TEXT        NOT NULL,
    designation TEXT        DEFAULT '',
    type        TEXT        NOT NULL,
    quantity    INTEGER     NOT NULL,
    notes       TEXT        DEFAULT '',
    timestamp   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS books (
    id                SERIAL PRIMARY KEY,
    code              TEXT DEFAULT '',
    title             TEXT NOT NULL,
    author            TEXT DEFAULT '',
    category          TEXT DEFAULT '',
    language          TEXT DEFAULT '',
    status            TEXT DEFAULT '',
    borrower          TEXT DEFAULT '',
    borrower_contact  TEXT DEFAULT '',
    loan_date         TEXT DEFAULT '',
    due_date          TEXT DEFAULT '',
    notes             TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS loans (
    id          SERIAL PRIMARY KEY,
    code        TEXT DEFAULT '',
    title       TEXT DEFAULT '',
    author      TEXT DEFAULT '',
    borrower    TEXT DEFAULT '',
    loan_date   TEXT DEFAULT '',
    due_date    TEXT DEFAULT '',
    loan_status TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS alerts (
    id       SERIAL PRIMARY KEY,
    location TEXT NOT NULL,
    type     TEXT DEFAULT '',
    item     TEXT DEFAULT ''
);
"""

# ── Helpers ───────────────────────────────────────────────

def _s(val):
    if pd.isna(val):
        return ""
    return str(val).strip()


def _n(val):
    if pd.isna(val):
        return None
    try:
        f = float(val)
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return None


def _i(val):
    n = _n(val)
    return int(n) if n is not None else None


# ── Excel readers (same logic as original data_loader.py) ─

def read_rex():
    df = pd.read_excel(os.path.join(DATA_DIR, "Rex.xlsx"), sheet_name="Inventaire 2026")
    rows = []
    for _, r in df.iterrows():
        desig = _s(r.get("Désignation", ""))
        if not desig:
            continue
        qty     = _i(r.get("Quantite"))
        current = _i(r.get("STOCK\nACTUEL"))
        rows.append({
            "ref":           _s(r.get("REF", "")),
            "designation":   desig,
            "designation_it": "",
            "category":      _s(r.get("Type", "")),
            "location":      "Rex",
            "room":          _s(r.get("Chambre", "")),
            "responsible":   _s(r.get("Utilisateur/responsable", "")),
            "brand":         _s(r.get("Marque", "")),
            "serial":        _s(r.get("Num de série ", "")),
            "owner":         _s(r.get("Origine ou Propriétaire ", "")),
            "quantity":      current if current is not None else qty,
            "min_quantity":  None,
            "condition":     "",
            "purchase_date": _s(r.get("Date d'achat  ou arrivée", "")),
            "cost":          _n(r.get("Cout\n(VAT incl.)")),
            "notes":         _s(r.get("REMARQUE", "")),
            "stock_initial": _i(r.get("Stock Initial")),
            "entries":       _i(r.get("Entrées Totales")),
            "exits":         _i(r.get("Sorties Totales")),
        })
    return rows


def read_inventaire(filename, sheet, location):
    df       = pd.read_excel(os.path.join(DATA_DIR, filename), sheet_name=sheet)
    desig_col = next(
        (c for c in ["DESIGNATION (FR)", "DESIGNATION", "DÉSIGNATION"] if c in df.columns),
        None
    )
    rows = []
    for _, r in df.iterrows():
        desig = _s(r.get(desig_col, "")) if desig_col else ""
        if not desig:
            continue
        rows.append({
            "ref":           str(int(r["N°"])) if pd.notna(r.get("N°")) else "",
            "designation":   desig,
            "designation_it": _s(r.get("DESIGNATION (IT)", "")),
            "category":      _s(r.get("CATÉGORIE", "")),
            "location":      location,
            "room":          _s(r.get("CHAMBRE", "") or r.get("EMPLACEMENT", "")),
            "responsible":   "",
            "brand":         "",
            "serial":        "",
            "owner":         "",
            "quantity":      _i(r.get("N PIECES")),
            "min_quantity":  _i(r.get("QUANTITÉ MINIMALE")),
            "condition":     _s(r.get("ÉTAT", "")),
            "purchase_date": _s(r.get("DATE_D_ENTRÉE", "")),
            "cost":          None,
            "notes":         _s(r.get("NOTES", "")),
            "stock_initial": None,
            "entries":       None,
            "exits":         None,
        })
    return rows


def read_alerts():
    alerts = []
    for filename, location in [("Ankofafa.xlsx", "Ankofafa"), ("Fille.xlsx", "Fille")]:
        try:
            df = pd.read_excel(os.path.join(DATA_DIR, filename), sheet_name="Matériel à contrôler")
        except Exception:
            continue
        for col in df.columns:
            col_str = str(col)
            if col_str.startswith("Unnamed") or col_str.startswith("Inventaire"):
                continue
            for val in df[col].dropna():
                v = str(val).strip()
                if v and v not in ("NaN", "nan"):
                    alerts.append({"location": location, "type": col_str, "item": v})
    return alerts


def read_biblioteca():
    path = os.path.join(DATA_DIR, "Biblioteca.xlsx")
    books = []
    for _, r in pd.read_excel(path, sheet_name="Lista Libri").iterrows():
        code  = _s(r.get("Codice Libro", ""))
        title = _s(r.get("Titolo", ""))
        if not title and not code:
            continue
        books.append({
            "code":             code,
            "title":            title,
            "author":           _s(r.get("Autore", "")),
            "category":         _s(r.get("Categoria", "")),
            "language":         _s(r.get("Lingua", "")),
            "status":           _s(r.get("Stato", "")),
            "borrower":         _s(r.get("Nome Prestatario", "")),
            "borrower_contact": _s(r.get("Contatto Prestatario", "")),
            "loan_date":        _s(r.get("Data Prestito", "")),
            "due_date":         _s(r.get("Data Restituzione Prevista (impostato a 30 gg dopo)", "")),
            "notes":            _s(r.get("Note", "")),
        })

    loans = []
    try:
        for _, r in pd.read_excel(path, sheet_name="Prestiti Attivi (non modificare").iterrows():
            title = _s(r.get("Titolo", ""))
            if not title:
                continue
            loans.append({
                "code":        _s(r.get("Codice Libro", "")),
                "title":       title,
                "author":      _s(r.get("Autore", "")),
                "borrower":    _s(r.get("Nome Prestatario", "")),
                "loan_date":   _s(r.get("Data Prestito", "")),
                "due_date":    _s(r.get("Data Scadenza", "")),
                "loan_status": _s(r.get("Stato Prestito", "")),
            })
    except Exception:
        pass
    return books, loans


def read_movements_json():
    path = os.path.join(DATA_DIR, "movements.json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Migration runner ──────────────────────────────────────

def run():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set. Add it to your .env file.")
        sys.exit(1)

    print("Connecting to Supabase...")
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    cur  = conn.cursor()

    print("Creating schema...")
    cur.execute(SCHEMA)
    conn.commit()

    # ── Users ──────────────────────────────────────────
    cur.execute("SELECT COUNT(*) AS n FROM users")
    if cur.fetchone()["n"] == 0:
        print("Inserting default users...")
        for uname, role, pwd in [
            ("admin",     "admin",     "Admin2024!"),
            ("educateur", "educateur", "Edu2024!"),
            ("logistic",  "logistic",  "Log2024!"),
        ]:
            cur.execute(
                "INSERT INTO users (username, role, password_hash) VALUES (%s, %s, %s)",
                (uname, role, generate_password_hash(pwd))
            )
        conn.commit()
        print("  OK 3 default users created")
    else:
        print("  - Users already present, skipping")

    # ── Inventory ──────────────────────────────────────
    cur.execute("SELECT COUNT(*) AS n FROM inventory")
    existing = cur.fetchone()["n"]
    if existing > 0 and not FORCE:
        print(f"  - Inventory already has {existing} rows (use --force to reimport)")
    else:
        if FORCE:
            cur.execute("TRUNCATE inventory RESTART IDENTITY CASCADE")
            conn.commit()
        items = []
        for reader, args in [
            (read_rex,       ()),
            (read_inventaire, ("Ankofafa.xlsx", "Inventaire_0126", "Ankofafa")),
            (read_inventaire, ("Fille.xlsx",    "Inventaire_0126", "Fille")),
        ]:
            try:
                items.extend(reader(*args))
            except Exception as e:
                print(f"  WARNING: could not read {args}: {e}")
        if items:
            psycopg2.extras.execute_batch(cur, """
                INSERT INTO inventory
                  (ref, designation, designation_it, category, location, room,
                   responsible, brand, serial, owner, quantity, min_quantity,
                   condition, purchase_date, cost, notes, stock_initial, entries, exits)
                VALUES
                  (%(ref)s, %(designation)s, %(designation_it)s, %(category)s,
                   %(location)s, %(room)s, %(responsible)s, %(brand)s, %(serial)s,
                   %(owner)s, %(quantity)s, %(min_quantity)s, %(condition)s,
                   %(purchase_date)s, %(cost)s, %(notes)s, %(stock_initial)s,
                   %(entries)s, %(exits)s)
            """, items)
            conn.commit()
            print(f"  OK {len(items)} inventory items inserted")
        else:
            print("  WARNING: no inventory items found — check that Excel files are in data/")

    # ── Alerts ─────────────────────────────────────────
    cur.execute("SELECT COUNT(*) AS n FROM alerts")
    if cur.fetchone()["n"] == 0 or FORCE:
        if FORCE:
            cur.execute("TRUNCATE alerts RESTART IDENTITY")
        alerts = read_alerts()
        if alerts:
            psycopg2.extras.execute_batch(cur,
                "INSERT INTO alerts (location, type, item) VALUES (%(location)s, %(type)s, %(item)s)",
                alerts
            )
            conn.commit()
            print(f"  OK {len(alerts)} alerts inserted")
    else:
        print("  - Alerts already present, skipping")

    # ── Books & loans ──────────────────────────────────
    cur.execute("SELECT COUNT(*) AS n FROM books")
    if cur.fetchone()["n"] == 0 or FORCE:
        if FORCE:
            cur.execute("TRUNCATE books RESTART IDENTITY")
            cur.execute("TRUNCATE loans RESTART IDENTITY")
        try:
            books, loans = read_biblioteca()
            if books:
                psycopg2.extras.execute_batch(cur, """
                    INSERT INTO books
                      (code, title, author, category, language, status,
                       borrower, borrower_contact, loan_date, due_date, notes)
                    VALUES
                      (%(code)s, %(title)s, %(author)s, %(category)s, %(language)s,
                       %(status)s, %(borrower)s, %(borrower_contact)s, %(loan_date)s,
                       %(due_date)s, %(notes)s)
                """, books)
                print(f"  OK {len(books)} books inserted")
            if loans:
                psycopg2.extras.execute_batch(cur, """
                    INSERT INTO loans (code, title, author, borrower, loan_date, due_date, loan_status)
                    VALUES (%(code)s, %(title)s, %(author)s, %(borrower)s, %(loan_date)s, %(due_date)s, %(loan_status)s)
                """, loans)
                print(f"  OK {len(loans)} loans inserted")
            conn.commit()
        except Exception as e:
            print(f"  WARNING: biblioteca import failed: {e}")
    else:
        print("  - Books already present, skipping")

    # ── Existing movements.json ─────────────────────────
    old_mvts = read_movements_json()
    if old_mvts:
        cur.execute("SELECT COUNT(*) AS n FROM movements")
        if cur.fetchone()["n"] == 0:
            print(f"  Migrating {len(old_mvts)} movements from movements.json...")
            for m in old_mvts:
                try:
                    ts = datetime.strptime(m["date"], "%Y-%m-%d %H:%M")
                except Exception:
                    ts = datetime.now()
                cur.execute(
                    "INSERT INTO movements (ref, location, designation, type, quantity, notes, timestamp) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (m["ref"], m["location"], m.get("designation", ""),
                     m["type"], m["quantity"], m.get("notes", ""), ts)
                )
            conn.commit()
            print(f"  OK {len(old_mvts)} movements migrated")

    cur.close()
    conn.close()
    print("\nMigration complete OK")


if __name__ == "__main__":
    run()
