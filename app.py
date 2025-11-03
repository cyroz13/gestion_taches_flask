from flask import Flask, render_template, request, redirect, flash
import sqlite3
from collections import OrderedDict

app = Flask(__name__)
app.secret_key = "change-moi-plus-tard"  # remplace par une vraie clé secrète

DB_PATH = "database.db"

def init_db_if_needed():
    """Crée la table si besoin et ajoute la colonne category si elle manque."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            done BOOLEAN NOT NULL CHECK (done IN (0, 1)),
            category TEXT DEFAULT 'Général'
        )
    """)
    # S'assurer que la colonne category existe (si table plus ancienne)
    cur.execute("PRAGMA table_info(tasks)")
    cols = [r[1] for r in cur.fetchall()]
    if "category" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN category TEXT DEFAULT 'Général'")
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_tasks():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title, done, category FROM tasks")
    rows = cur.fetchall()
    conn.close()
    return rows

def add_task_to_db(title, category):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tasks (title, done, category) VALUES (?, ?, ?)",
        (title, 0, category)
    )
    conn.commit()
    conn.close()

def mark_task_done_in_db(task_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET done = 1 WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

def delete_task_from_db(task_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

# ---------- Catégories ----------
def get_categories():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT category FROM tasks ORDER BY category COLLATE NOCASE")
    cats = [r[0] for r in cur.fetchall()]
    conn.close()
    return cats

def rename_category_in_db(old, new):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET category = ? WHERE category = ?", (new, old))
    conn.commit()
    conn.close()

# ---------- Routes ----------
@app.route("/")
def home():
    init_db_if_needed()
    tasks = get_tasks()

    # Grouper : "à faire" par catégorie / "terminées" global
    grouped_todo = {}
    all_done = []
    for t in tasks:
        cat = t["category"] or "Général"
        if t["done"]:
            all_done.append(t)
        else:
            grouped_todo.setdefault(cat, []).append(t)

    # Tri alphabétique des catégories
    groups = OrderedDict(sorted(grouped_todo.items(), key=lambda kv: kv[0].lower()))
    return render_template("index.html", groups=groups, all_done=all_done)

@app.route("/add", methods=["POST"])
def add():
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "Général").strip()
    if title:
        add_task_to_db(title, category)
        flash(f"Tâche ajoutée dans « {category} » ✅", "success")
    else:
        flash("Le titre est vide.", "danger")
    return redirect("/")

@app.route("/done/<int:task_id>", methods=["POST"])
def done(task_id):
    mark_task_done_in_db(task_id)
    flash("Tâche marquée comme terminée ✔️", "info")
    return redirect("/")

@app.route("/delete/<int:task_id>", methods=["POST"])
def delete(task_id):
    delete_task_from_db(task_id)
    flash("Tâche supprimée 🗑", "warning")
    return redirect("/")

@app.route("/categories", methods=["GET"])
def categories_page():
    init_db_if_needed()
    cats = get_categories()
    return render_template("categories.html", categories=cats)

@app.route("/rename_category", methods=["POST"])
def rename_category():
    old = request.form.get("old", "").strip()
    new = request.form.get("new", "").strip()
    if not old or not new:
        flash("Nom invalide.", "danger")
        return redirect("/categories")
    if old == new:
        flash("Le nouveau nom est identique.", "warning")
        return redirect("/categories")
    rename_category_in_db(old, new)
    flash(f"Catégorie « {old} » renommée en « {new} » ✅", "success")
    return redirect("/categories")

if __name__ == "__main__":
    app.run(debug=True)
