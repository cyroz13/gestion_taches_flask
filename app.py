from flask import Flask, render_template, request, redirect
import sqlite3
import os

app = Flask(__name__)

DB_PATH = "database.db"

def init_db_if_needed():
    # crée la base et la table si elles n'existent pas
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            done BOOLEAN NOT NULL CHECK (done IN (0, 1))
        )
    """)
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_tasks():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, done FROM tasks")
    tasks = cursor.fetchall()
    conn.close()
    return tasks

def add_task_to_db(title):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tasks (title, done) VALUES (?, ?)",
        (title, 0)
    )
    conn.commit()
    conn.close()

def mark_task_done_in_db(task_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE tasks SET done = 1 WHERE id = ?",
        (task_id,)
    )
    conn.commit()
    conn.close()

def delete_task_from_db(task_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM tasks WHERE id = ?",
        (task_id,)
    )
    conn.commit()
    conn.close()

@app.route("/")
def home():
    init_db_if_needed()  # sécurité : s'assure que la table existe
    tasks = get_tasks()
    return render_template("index.html", tasks=tasks)

@app.route("/add", methods=["POST"])
def add():
    title = request.form.get("title", "").strip()
    if title:
        add_task_to_db(title)
    return redirect("/")

@app.route("/done/<int:task_id>", methods=["POST"])
def done(task_id):
    mark_task_done_in_db(task_id)
    return redirect("/")

@app.route("/delete/<int:task_id>", methods=["POST"])
def delete(task_id):
    delete_task_from_db(task_id)
    return redirect("/")

if __name__ == "__main__":
    # en local tu continues à lancer comme avant
    app.run(debug=True)
