import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DB_PATH = Path(os.getenv("DATABASE_PATH", ROOT / "team_tasks.db"))
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
PORT = int(os.getenv("PORT", "8000"))
STATUSES = {"To Do", "In Progress", "Done"}
PRIORITIES = {"Low", "Medium", "High", "Urgent"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_members (
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('Admin', 'Member')),
                joined_at TEXT NOT NULL,
                PRIMARY KEY (project_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                due_date TEXT NOT NULL,
                priority TEXT NOT NULL CHECK (priority IN ('Low', 'Medium', 'High', 'Urgent')),
                status TEXT NOT NULL CHECK (status IN ('To Do', 'In Progress', 'Done')),
                assigned_to INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


def row_to_dict(row):
    return dict(row) if row else None


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 150_000)
    return f"pbkdf2_sha256${salt}${base64.b64encode(digest).decode()}"


def verify_password(password, stored):
    try:
        _, salt, digest = stored.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 150_000)
        return hmac.compare_digest(base64.b64encode(actual).decode(), digest)
    except ValueError:
        return False


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_token(user):
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64url(
        json.dumps(
            {"sub": user["id"], "name": user["name"], "email": user["email"], "exp": int(time.time()) + 86400},
            separators=(",", ":"),
        ).encode()
    )
    message = f"{header}.{payload}".encode()
    signature = b64url(hmac.new(JWT_SECRET.encode(), message, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def decode_token(token):
    try:
        header, payload, signature = token.split(".")
        expected = b64url(hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if claims.get("exp", 0) < int(time.time()):
            return None
        return claims
    except Exception:
        return None


def validate_required(data, fields):
    missing = [field for field in fields if not str(data.get(field, "")).strip()]
    if missing:
        return f"Missing required field(s): {', '.join(missing)}"
    return None


def membership(conn, project_id, user_id):
    return conn.execute(
        "SELECT role FROM project_members WHERE project_id = ? AND user_id = ?",
        (project_id, user_id),
    ).fetchone()


def task_with_names(conn, task_id):
    return conn.execute(
        """
        SELECT t.*, u.name AS assignee_name, creator.name AS creator_name, p.name AS project_name
        FROM tasks t
        LEFT JOIN users u ON u.id = t.assigned_to
        JOIN users creator ON creator.id = t.created_by
        JOIN projects p ON p.id = t.project_id
        WHERE t.id = ?
        """,
        (task_id,),
    ).fetchone()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def error(self, message, status=HTTPStatus.BAD_REQUEST):
        self.send_json({"error": message}, status)

    def body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode())
        except json.JSONDecodeError:
            return {}

    def current_user(self, conn):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        claims = decode_token(auth.removeprefix("Bearer ").strip())
        if not claims:
            return None
        return conn.execute("SELECT id, name, email, created_at FROM users WHERE id = ?", (claims["sub"],)).fetchone()

    def require_user(self, conn):
        user = self.current_user(conn)
        if not user:
            self.error("Authentication required", HTTPStatus.UNAUTHORIZED)
            return None
        return user

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.route("GET")
        else:
            self.serve_static()

    def do_POST(self):
        self.route("POST")

    def do_PATCH(self):
        self.route("PATCH")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        parts = [part for part in path.split("/") if part]
        data = self.body()

        try:
            with db() as conn:
                if path == "/api/auth/signup" and method == "POST":
                    return self.signup(conn, data)
                if path == "/api/auth/login" and method == "POST":
                    return self.login(conn, data)

                user = self.require_user(conn)
                if not user:
                    return

                if path == "/api/me" and method == "GET":
                    return self.send_json({"user": row_to_dict(user)})
                if path == "/api/projects" and method == "GET":
                    return self.projects(conn, user)
                if path == "/api/projects" and method == "POST":
                    return self.create_project(conn, user, data)
                if path == "/api/dashboard" and method == "GET":
                    return self.dashboard(conn, user, parse_qs(parsed.query))
                if len(parts) == 3 and parts[:2] == ["api", "projects"] and method == "GET":
                    return self.project_detail(conn, user, int(parts[2]))
                if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "tasks":
                    if method == "GET":
                        return self.tasks(conn, user, int(parts[2]))
                    if method == "POST":
                        return self.create_task(conn, user, int(parts[2]), data)
                if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "members" and method == "POST":
                    return self.add_member(conn, user, int(parts[2]), data)
                if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "members" and method == "DELETE":
                    return self.remove_member(conn, user, int(parts[2]), int(parts[4]))
                if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                    if method == "PATCH":
                        return self.update_task(conn, user, int(parts[2]), data)
                    if method == "DELETE":
                        return self.delete_task(conn, user, int(parts[2]))
                return self.error("Route not found", HTTPStatus.NOT_FOUND)
        except sqlite3.IntegrityError as exc:
            self.error("Database constraint failed. Check duplicate emails, member assignment, and valid values.", HTTPStatus.CONFLICT)
        except ValueError:
            self.error("Invalid route parameter", HTTPStatus.BAD_REQUEST)

    def signup(self, conn, data):
        error = validate_required(data, ["name", "email", "password"])
        if error:
            return self.error(error)
        if len(data["password"]) < 8:
            return self.error("Password must be at least 8 characters")
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (data["name"].strip(), data["email"].strip().lower(), hash_password(data["password"]), now_iso()),
        )
        user = conn.execute("SELECT id, name, email, created_at FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        self.send_json({"user": row_to_dict(user), "token": sign_token(user)}, HTTPStatus.CREATED)

    def login(self, conn, data):
        error = validate_required(data, ["email", "password"])
        if error:
            return self.error(error)
        user = conn.execute("SELECT * FROM users WHERE email = ?", (data["email"].strip().lower(),)).fetchone()
        if not user or not verify_password(data["password"], user["password_hash"]):
            return self.error("Invalid email or password", HTTPStatus.UNAUTHORIZED)
        public = conn.execute("SELECT id, name, email, created_at FROM users WHERE id = ?", (user["id"],)).fetchone()
        self.send_json({"user": row_to_dict(public), "token": sign_token(public)})

    def projects(self, conn, user):
        rows = conn.execute(
            """
            SELECT p.*, pm.role,
                   COUNT(t.id) AS task_count,
                   SUM(CASE WHEN t.status = 'Done' THEN 1 ELSE 0 END) AS done_count
            FROM projects p
            JOIN project_members pm ON pm.project_id = p.id
            LEFT JOIN tasks t ON t.project_id = p.id
            WHERE pm.user_id = ?
            GROUP BY p.id, pm.role
            ORDER BY p.created_at DESC
            """,
            (user["id"],),
        ).fetchall()
        self.send_json({"projects": [row_to_dict(row) for row in rows]})

    def create_project(self, conn, user, data):
        error = validate_required(data, ["name"])
        if error:
            return self.error(error)
        cur = conn.execute(
            "INSERT INTO projects (name, description, created_by, created_at) VALUES (?, ?, ?, ?)",
            (data["name"].strip(), data.get("description", "").strip(), user["id"], now_iso()),
        )
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role, joined_at) VALUES (?, ?, 'Admin', ?)",
            (cur.lastrowid, user["id"], now_iso()),
        )
        self.project_detail(conn, user, cur.lastrowid, HTTPStatus.CREATED)

    def project_detail(self, conn, user, project_id, status=HTTPStatus.OK):
        role = membership(conn, project_id, user["id"])
        if not role:
            return self.error("You do not belong to this project", HTTPStatus.FORBIDDEN)
        project = conn.execute(
            "SELECT p.*, ? AS role FROM projects p WHERE p.id = ?",
            (role["role"], project_id),
        ).fetchone()
        members = conn.execute(
            """
            SELECT u.id, u.name, u.email, pm.role, pm.joined_at
            FROM project_members pm
            JOIN users u ON u.id = pm.user_id
            WHERE pm.project_id = ?
            ORDER BY pm.role, u.name
            """,
            (project_id,),
        ).fetchall()
        self.send_json({"project": row_to_dict(project), "members": [row_to_dict(row) for row in members]}, status)

    def add_member(self, conn, user, project_id, data):
        role = membership(conn, project_id, user["id"])
        if not role or role["role"] != "Admin":
            return self.error("Only project admins can add members", HTTPStatus.FORBIDDEN)
        error = validate_required(data, ["email"])
        if error:
            return self.error(error)
        target = conn.execute("SELECT id FROM users WHERE email = ?", (data["email"].strip().lower(),)).fetchone()
        if not target:
            return self.error("No registered user found with that email", HTTPStatus.NOT_FOUND)
        member_role = data.get("role", "Member")
        if member_role not in {"Admin", "Member"}:
            return self.error("Role must be Admin or Member")
        conn.execute(
            "INSERT OR REPLACE INTO project_members (project_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
            (project_id, target["id"], member_role, now_iso()),
        )
        self.project_detail(conn, user, project_id)

    def remove_member(self, conn, user, project_id, member_id):
        role = membership(conn, project_id, user["id"])
        if not role or role["role"] != "Admin":
            return self.error("Only project admins can remove members", HTTPStatus.FORBIDDEN)
        admins = conn.execute(
            "SELECT COUNT(*) AS count FROM project_members WHERE project_id = ? AND role = 'Admin'",
            (project_id,),
        ).fetchone()["count"]
        target_role = membership(conn, project_id, member_id)
        if target_role and target_role["role"] == "Admin" and admins <= 1:
            return self.error("A project must keep at least one admin")
        conn.execute("DELETE FROM project_members WHERE project_id = ? AND user_id = ?", (project_id, member_id))
        conn.execute("UPDATE tasks SET assigned_to = NULL WHERE project_id = ? AND assigned_to = ?", (project_id, member_id))
        self.project_detail(conn, user, project_id)

    def tasks(self, conn, user, project_id):
        role = membership(conn, project_id, user["id"])
        if not role:
            return self.error("You do not belong to this project", HTTPStatus.FORBIDDEN)
        where = "WHERE t.project_id = ?"
        params = [project_id]
        if role["role"] != "Admin":
            where += " AND t.assigned_to = ?"
            params.append(user["id"])
        rows = conn.execute(
            f"""
            SELECT t.*, u.name AS assignee_name, creator.name AS creator_name, p.name AS project_name
            FROM tasks t
            LEFT JOIN users u ON u.id = t.assigned_to
            JOIN users creator ON creator.id = t.created_by
            JOIN projects p ON p.id = t.project_id
            {where}
            ORDER BY
              CASE t.status WHEN 'To Do' THEN 1 WHEN 'In Progress' THEN 2 ELSE 3 END,
              date(t.due_date)
            """,
            params,
        ).fetchall()
        self.send_json({"tasks": [row_to_dict(row) for row in rows]})

    def create_task(self, conn, user, project_id, data):
        role = membership(conn, project_id, user["id"])
        if not role or role["role"] != "Admin":
            return self.error("Only project admins can create tasks", HTTPStatus.FORBIDDEN)
        error = validate_required(data, ["title", "due_date", "priority"])
        if error:
            return self.error(error)
        if data["priority"] not in PRIORITIES:
            return self.error("Invalid priority")
        assigned_to = data.get("assigned_to") or None
        if assigned_to and not membership(conn, project_id, int(assigned_to)):
            return self.error("Assignee must be a project member")
        cur = conn.execute(
            """
            INSERT INTO tasks (project_id, title, description, due_date, priority, status, assigned_to, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'To Do', ?, ?, ?, ?)
            """,
            (
                project_id,
                data["title"].strip(),
                data.get("description", "").strip(),
                data["due_date"],
                data["priority"],
                assigned_to,
                user["id"],
                now_iso(),
                now_iso(),
            ),
        )
        self.send_json({"task": row_to_dict(task_with_names(conn, cur.lastrowid))}, HTTPStatus.CREATED)

    def update_task(self, conn, user, task_id, data):
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return self.error("Task not found", HTTPStatus.NOT_FOUND)
        role = membership(conn, task["project_id"], user["id"])
        if not role:
            return self.error("You do not belong to this project", HTTPStatus.FORBIDDEN)
        is_admin = role["role"] == "Admin"
        is_assignee = task["assigned_to"] == user["id"]
        if not is_admin and not is_assignee:
            return self.error("Members can only update assigned tasks", HTTPStatus.FORBIDDEN)

        allowed = {"status"} if not is_admin else {"title", "description", "due_date", "priority", "status", "assigned_to"}
        changes = {key: data[key] for key in allowed if key in data}
        if "status" in changes and changes["status"] not in STATUSES:
            return self.error("Invalid status")
        if "priority" in changes and changes["priority"] not in PRIORITIES:
            return self.error("Invalid priority")
        if "assigned_to" in changes and changes["assigned_to"] and not membership(conn, task["project_id"], int(changes["assigned_to"])):
            return self.error("Assignee must be a project member")
        if not changes:
            return self.error("No allowed fields supplied")
        assignments = ", ".join([f"{key} = ?" for key in changes]) + ", updated_at = ?"
        values = list(changes.values()) + [now_iso(), task_id]
        conn.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", values)
        self.send_json({"task": row_to_dict(task_with_names(conn, task_id))})

    def delete_task(self, conn, user, task_id):
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return self.error("Task not found", HTTPStatus.NOT_FOUND)
        role = membership(conn, task["project_id"], user["id"])
        if not role or role["role"] != "Admin":
            return self.error("Only project admins can delete tasks", HTTPStatus.FORBIDDEN)
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.send_json({"ok": True})

    def dashboard(self, conn, user, query):
        project_id = query.get("project_id", [None])[0]
        filters = ["pm.user_id = ?"]
        params = [user["id"]]
        if project_id:
            filters.append("p.id = ?")
            params.append(project_id)
        rows = conn.execute(
            f"""
            SELECT t.*, p.name AS project_name, u.name AS assignee_name, pm.role AS viewer_role
            FROM tasks t
            JOIN projects p ON p.id = t.project_id
            JOIN project_members pm ON pm.project_id = p.id
            LEFT JOIN users u ON u.id = t.assigned_to
            WHERE {' AND '.join(filters)}
            """,
            params,
        ).fetchall()
        visible = [row_to_dict(row) for row in rows if row["viewer_role"] == "Admin" or row["assigned_to"] == user["id"]]
        by_status = {status: 0 for status in STATUSES}
        by_priority = {priority: 0 for priority in PRIORITIES}
        per_user = {}
        today = datetime.now(timezone.utc).date().isoformat()
        overdue = 0
        due_soon = 0
        unassigned = 0
        high_priority_open = 0
        next_due = None
        for task in visible:
            by_status[task["status"]] += 1
            by_priority[task["priority"]] += 1
            assignee = task.get("assignee_name") or "Unassigned"
            per_user[assignee] = per_user.get(assignee, 0) + 1
            if not task["assigned_to"]:
                unassigned += 1
            if task["status"] != "Done" and task["due_date"] < today:
                overdue += 1
            if task["status"] != "Done" and today <= task["due_date"] <= datetime.fromtimestamp(time.time() + 7 * 86400, timezone.utc).date().isoformat():
                due_soon += 1
            if task["status"] != "Done" and task["priority"] in {"High", "Urgent"}:
                high_priority_open += 1
            if task["status"] != "Done" and (next_due is None or task["due_date"] < next_due["due_date"]):
                next_due = task
        total = len(visible)
        done = by_status["Done"]
        self.send_json(
            {
                "total_tasks": total,
                "by_status": by_status,
                "by_priority": by_priority,
                "per_user": per_user,
                "overdue": overdue,
                "due_soon": due_soon,
                "unassigned": unassigned,
                "high_priority_open": high_priority_open,
                "completion_rate": round((done / total) * 100) if total else 0,
                "active_tasks": total - done,
                "next_due": next_due,
                "recent": sorted(visible, key=lambda item: item["updated_at"], reverse=True)[:6],
            }
        )

    def serve_static(self):
        parsed = urlparse(self.path)
        requested = parsed.path.lstrip("/") or "index.html"
        file_path = (STATIC_DIR / requested).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.exists():
            file_path = STATIC_DIR / "index.html"
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_types.get(file_path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Team Task Manager running on http://localhost:{PORT}")
    server.serve_forever()
