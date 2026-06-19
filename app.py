from flask import Flask, request, jsonify
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os

app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-prod")
CORS(app, resources={r"/api/*": {"origins": [
    "http://localhost:4200",
    "https://kaiyuanservice.com",
    "https://www.kaiyuanservice.com"
]}})

jwt = JWTManager(app)
DB_PATH = "database.db"


# ---------- DB ----------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            done BOOLEAN NOT NULL CHECK (done IN (0,1)) DEFAULT 0,
            category TEXT DEFAULT 'Général',
            user_id INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS user_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            position INTEGER,
            UNIQUE(user_id, name),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS project_shares (
            project_id INTEGER NOT NULL,
            viewer_id INTEGER NOT NULL,
            can_edit BOOLEAN NOT NULL CHECK (can_edit IN (0,1)) DEFAULT 0,
            PRIMARY KEY (project_id, viewer_id),
            FOREIGN KEY(project_id) REFERENCES user_categories(id),
            FOREIGN KEY(viewer_id) REFERENCES users(id)
        )""")
        conn.commit()


# ---------- Helpers ----------

def find_user_by_username(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return row["id"] if row else None

def get_projects_for(uid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, COALESCE(position, 0) as position
            FROM user_categories
            WHERE user_id = ?
            ORDER BY position ASC, name COLLATE NOCASE
        """, (uid,))
        rows = cur.fetchall()
    return [{"id": r["id"], "name": r["name"], "position": r["position"]} for r in rows]


# ---------- Auth ----------

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "Nom d'utilisateur et mot de passe requis."}), 400
    pw_hash = generate_password_hash(password)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, pw_hash))
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        token = create_access_token(identity=str(user_id))
        return jsonify({"access_token": token, "username": username}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Nom d'utilisateur déjà pris."}), 409

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Identifiants invalides."}), 401
    token = create_access_token(identity=str(row["id"]))
    return jsonify({"access_token": token, "username": username})


# ---------- Tâches ----------

@app.route("/api/tasks", methods=["GET"])
@jwt_required()
def get_tasks():
    uid = int(get_jwt_identity())
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT t.id, t.title, t.done, t.category
        FROM tasks t WHERE t.user_id = ?
        UNION
        SELECT t.id, t.title, t.done, t.category
        FROM project_shares ps
        JOIN user_categories uc ON uc.id = ps.project_id
        JOIN tasks t ON t.user_id = uc.user_id AND t.category = uc.name
        WHERE ps.viewer_id = ?
        ORDER BY 1
    """, (uid, uid))
    tasks = [{"id": r["id"], "title": r["title"], "done": bool(r["done"]), "category": r["category"]}
             for r in cur.fetchall()]
    conn.close()

    projects_full = get_projects_for(uid)
    proj_names = [p["name"] for p in projects_full]
    for t in tasks:
        if t["category"] not in proj_names:
            proj_names.append(t["category"])

    return jsonify({"tasks": tasks, "projects": proj_names, "projects_full": projects_full})

@app.route("/api/tasks", methods=["POST"])
@jwt_required()
def add_task():
    uid = int(get_jwt_identity())
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    project = (data.get("project") or "Général").strip()
    if not title:
        return jsonify({"error": "Le titre est vide."}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO tasks (title, done, category, user_id) VALUES (?, 0, ?, ?)", (title, project, uid))
    conn.commit()
    task_id = cur.lastrowid
    conn.close()
    return jsonify({"id": task_id, "title": title, "done": False, "project": project}), 201

@app.route("/api/tasks/<int:task_id>/done", methods=["POST"])
@jwt_required()
def done_task(task_id):
    uid = int(get_jwt_identity())
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id, category FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Tâche introuvable."}), 404
    owner_id = row["user_id"]
    if owner_id != uid:
        cur.execute("""
            SELECT ps.can_edit FROM project_shares ps
            JOIN user_categories uc ON uc.id = ps.project_id
            WHERE uc.user_id = ? AND uc.name = ? AND ps.viewer_id = ?
        """, (owner_id, row["category"], uid))
        share = cur.fetchone()
        if not share or not share["can_edit"]:
            conn.close()
            return jsonify({"error": "Accès refusé."}), 403
    cur.execute("UPDATE tasks SET done = 1 WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@jwt_required()
def delete_task(task_id):
    uid = int(get_jwt_identity())
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Tâche introuvable."}), 404
    if row["user_id"] != uid:
        conn.close()
        return jsonify({"error": "Accès refusé."}), 403
    cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------- Projets ----------

@app.route("/api/projects", methods=["GET"])
@jwt_required()
def list_projects():
    uid = int(get_jwt_identity())
    return jsonify(get_projects_for(uid))

@app.route("/api/projects", methods=["POST"])
@jwt_required()
def add_project():
    uid = int(get_jwt_identity())
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nom vide."}), 400
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM user_categories WHERE user_id = ?", (uid,))
        next_pos = cur.fetchone()[0]
        cur.execute("INSERT OR IGNORE INTO user_categories (user_id, name, position) VALUES (?, ?, ?)",
                    (uid, name, next_pos))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({"error": "Projet déjà existant."}), 409
    return jsonify({"name": name, "position": next_pos}), 201

@app.route("/api/projects/<int:proj_id>/up", methods=["POST"])
@jwt_required()
def project_up(proj_id):
    uid = int(get_jwt_identity())
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT position FROM user_categories WHERE id = ? AND user_id = ?", (proj_id, uid))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Introuvable."}), 404
        pos = row[0] or 0
        cur.execute("""SELECT id, position FROM user_categories
                       WHERE user_id = ? AND position < ? ORDER BY position DESC LIMIT 1""", (uid, pos))
        above = cur.fetchone()
        if above:
            cur.execute("UPDATE user_categories SET position = ? WHERE id = ?", (above[1], proj_id))
            cur.execute("UPDATE user_categories SET position = ? WHERE id = ?", (pos, above[0]))
            conn.commit()
    return jsonify(get_projects_for(uid))

@app.route("/api/projects/<int:proj_id>/down", methods=["POST"])
@jwt_required()
def project_down(proj_id):
    uid = int(get_jwt_identity())
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT position FROM user_categories WHERE id = ? AND user_id = ?", (proj_id, uid))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Introuvable."}), 404
        pos = row[0] or 0
        cur.execute("""SELECT id, position FROM user_categories
                       WHERE user_id = ? AND position > ? ORDER BY position ASC LIMIT 1""", (uid, pos))
        below = cur.fetchone()
        if below:
            cur.execute("UPDATE user_categories SET position = ? WHERE id = ?", (below[1], proj_id))
            cur.execute("UPDATE user_categories SET position = ? WHERE id = ?", (pos, below[0]))
            conn.commit()
    return jsonify(get_projects_for(uid))


# ---------- Partage par projet ----------

@app.route("/api/projects/<int:proj_id>/shares", methods=["GET"])
@jwt_required()
def list_project_shares(proj_id):
    uid = int(get_jwt_identity())
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM user_categories WHERE id = ? AND user_id = ?", (proj_id, uid))
    if not cur.fetchone():
        conn.close()
        return jsonify({"error": "Projet introuvable."}), 404
    cur.execute("""
        SELECT u.username, ps.can_edit
        FROM project_shares ps
        JOIN users u ON u.id = ps.viewer_id
        WHERE ps.project_id = ?
    """, (proj_id,))
    shares = [{"username": r["username"], "can_edit": bool(r["can_edit"])} for r in cur.fetchall()]
    conn.close()
    return jsonify(shares)

@app.route("/api/projects/<int:proj_id>/shares", methods=["POST"])
@jwt_required()
def share_project(proj_id):
    uid = int(get_jwt_identity())
    data = request.get_json() or {}
    target_username = (data.get("username") or "").strip()
    can_edit = bool(data.get("can_edit", False))
    if not target_username:
        return jsonify({"error": "Nom d'utilisateur requis."}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM user_categories WHERE id = ? AND user_id = ?", (proj_id, uid))
    if not cur.fetchone():
        conn.close()
        return jsonify({"error": "Projet introuvable."}), 404
    target_id = find_user_by_username(target_username)
    if not target_id:
        conn.close()
        return jsonify({"error": "Utilisateur introuvable."}), 404
    if target_id == uid:
        conn.close()
        return jsonify({"error": "Impossible de te partager à toi-même."}), 400
    cur.execute("INSERT OR REPLACE INTO project_shares (project_id, viewer_id, can_edit) VALUES (?, ?, ?)",
                (proj_id, target_id, 1 if can_edit else 0))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/projects/<int:proj_id>/shares", methods=["DELETE"])
@jwt_required()
def unshare_project(proj_id):
    uid = int(get_jwt_identity())
    data = request.get_json() or {}
    target_username = (data.get("username") or "").strip()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM user_categories WHERE id = ? AND user_id = ?", (proj_id, uid))
    if not cur.fetchone():
        conn.close()
        return jsonify({"error": "Projet introuvable."}), 404
    target_id = find_user_by_username(target_username)
    if not target_id:
        conn.close()
        return jsonify({"error": "Utilisateur introuvable."}), 404
    cur.execute("DELETE FROM project_shares WHERE project_id = ? AND viewer_id = ?", (proj_id, target_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
