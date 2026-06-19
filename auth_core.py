#!/usr/bin/env python3
import os
import secrets
import hashlib
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, flash, redirect, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


LOGIN_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }}</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;min-height:100dvh;display:flex;align-items:center;justify-content:center;padding:32px;background:#080d1a;color:#eef4ff;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}
main{width:min(420px,100%);background:#111a2e;border:1px solid #263655;border-radius:18px;padding:24px;box-shadow:0 20px 70px #0008}
h1{margin:0 0 8px;font-size:26px}p{color:#aebbdd;line-height:1.45}.msg{padding:10px 12px;border:1px solid #334360;background:#0d1426;border-radius:12px;margin:10px 0;color:#dbe6ff}
label{display:block;margin:14px 0 6px;color:#c7d4f2;font-size:13px}input{width:100%;box-sizing:border-box;background:#0d1426;color:#eef4ff;border:1px solid #2f3d60;border-radius:12px;padding:12px}
button{width:100%;margin-top:16px;background:#18a88f;color:#06131b;border:0;border-radius:12px;padding:12px;font-weight:800;cursor:pointer}
a{color:#9cc8ff}.links{display:flex;justify-content:space-between;gap:12px;margin-top:16px;font-size:14px}
@media(max-width:640px){body{align-items:center;justify-content:center;padding:24px 16px}main{margin:0;padding:22px 18px;border-radius:16px}h1{font-size:24px}}
</style></head><body><main>
<h1>{{ title }}</h1>
{% for message in get_flashed_messages() %}<div class="msg">{{ message }}</div>{% endfor %}
{{ body|safe }}
</main></body></html>"""


class AuthManager:
    def __init__(self, base_dir: Path, app_name: str):
        self.base_dir = base_dir
        self.app_name = app_name
        self.state_dir = Path(os.environ.get("DASHBOARD_AUTH_DIR", base_dir / "state"))
        self.db_path = self.state_dir / "auth.sqlite3"

    def init_app(self, app: Flask) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY") or self._secret_key()
        app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
        self.init_db()

        app.add_url_rule("/login", view_func=self.login, methods=["GET", "POST"])
        app.add_url_rule("/logout", view_func=self.logout, methods=["POST"])
        app.add_url_rule("/request-password", view_func=self.request_password, methods=["GET", "POST"])
        app.add_url_rule("/set-password/<code>", view_func=self.set_password, methods=["GET", "POST"])

    def _secret_key(self) -> str:
        key_path = self.state_dir / "flask-secret"
        if not key_path.exists():
            key_path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            key_path.chmod(0o600)
        return key_path.read_text(encoding="utf-8").strip()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    password_hash TEXT,
                    confirmed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS password_links (
                    code_hash TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_or_update_user(self, email: str, password: str, confirmed: bool = True) -> None:
        now = self.now()
        confirmed_at = now if confirmed else None
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users(email, password_hash, confirmed_at, created_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    password_hash=excluded.password_hash,
                    confirmed_at=COALESCE(excluded.confirmed_at, users.confirmed_at)
                """,
                (self.clean_email(email), generate_password_hash(password), confirmed_at, now),
            )

    def require_login(self, view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            trusted_user = self.clean_email(request.headers.get("X-OpenClaw-User"))
            if trusted_user and request.remote_addr in {"127.0.0.1", "::1"}:
                session["user_email"] = trusted_user
                return view(*args, **kwargs)
            if not session.get("user_email"):
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)

        return wrapped

    def login(self):
        if request.method == "POST":
            email = self.clean_email(request.form.get("email"))
            password = request.form.get("password") or ""
            user = self.user(email)
            if user and user["confirmed_at"] and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_email"] = email
                return redirect(request.args.get("next") or url_for("index"))
            flash("Usuario o contraseña incorrectos.")
        body = """
        <form method="post">
          <label>Email</label><input name="email" type="email" autocomplete="username" required autofocus>
          <label>Contraseña</label><input name="password" type="password" autocomplete="current-password" required>
          <button type="submit">Entrar</button>
        </form>
        <div class="links"><a href="/request-password">Alta o recuperar contraseña</a></div>
        """
        return self.page("Acceso al dashboard", body)

    def logout(self):
        session.clear()
        return redirect(url_for("login"))

    def request_password(self):
        if request.method == "POST":
            email = self.clean_email(request.form.get("email"))
            if self.can_request_link(email):
                code = self.create_password_link(email)
                self.send_password_email(email, code)
            flash("Si el email está autorizado, recibirás un enlace de confirmación.")
        body = """
        <p>Introduce tu email para recibir un enlace de alta inicial o recuperación de contraseña.</p>
        <form method="post">
          <label>Email</label><input name="email" type="email" autocomplete="email" required autofocus>
          <button type="submit">Enviar email</button>
        </form>
        <div class="links"><a href="/login">Volver al login</a></div>
        """
        return self.page("Alta o recuperación", body)

    def set_password(self, code: str):
        link = self.valid_link(code)
        if not link:
            return self.page("Enlace no válido", "<p>El enlace ha caducado o ya se ha usado.</p><div class='links'><a href='/request-password'>Pedir otro enlace</a></div>"), 400
        if request.method == "POST":
            password = request.form.get("password") or ""
            confirm = request.form.get("confirm") or ""
            if len(password) < 6:
                flash("La contraseña debe tener al menos 6 caracteres.")
            elif password != confirm:
                flash("Las contraseñas no coinciden.")
            else:
                self.create_or_update_user(link["email"], password, confirmed=True)
                self.consume_link(code)
                flash("Contraseña actualizada. Ya puedes entrar.")
                return redirect(url_for("login"))
        body = f"""
        <p>Email confirmado: <strong>{link['email']}</strong></p>
        <form method="post">
          <label>Nueva contraseña</label><input name="password" type="password" autocomplete="new-password" required autofocus>
          <label>Confirmar contraseña</label><input name="confirm" type="password" autocomplete="new-password" required>
          <button type="submit">Guardar contraseña</button>
        </form>
        """
        return self.page("Definir contraseña", body)

    def page(self, title: str, body: str):
        return render_template_string(LOGIN_HTML, title=title, body=body)

    def user(self, email: str):
        with self.connect() as conn:
            return conn.execute("SELECT * FROM users WHERE email = ?", (self.clean_email(email),)).fetchone()

    def user_count(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def can_request_link(self, email: str) -> bool:
        if not email:
            return False
        if self.user(email):
            return True
        allowed = {e.strip().lower() for e in os.environ.get("DASHBOARD_ALLOWED_EMAILS", "").split(",") if e.strip()}
        return self.user_count() == 0 or email in allowed

    def create_password_link(self, email: str) -> str:
        code = secrets.token_urlsafe(32)
        now = self.now()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO password_links(code_hash, email, expires_at, created_at) VALUES(?, ?, ?, ?)",
                (self.hash_code(code), self.clean_email(email), expires, now),
            )
        return code

    def valid_link(self, code: str):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM password_links WHERE code_hash = ? AND used_at IS NULL",
                (self.hash_code(code),),
            ).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            return None
        return row

    def consume_link(self, code: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE password_links SET used_at = ? WHERE code_hash = ?", (self.now(), self.hash_code(code)))

    def send_password_email(self, email: str, code: str) -> None:
        base_url = os.environ.get("DASHBOARD_PUBLIC_URL") or request.host_url.rstrip("/")
        link = f"{base_url}/set-password/{code}"
        subject = f"{self.app_name}: enlace de acceso"
        body = f"Confirma este email y define tu contraseña aquí:\n\n{link}\n\nEl enlace caduca en 30 minutos."
        sender = os.environ.get("DASHBOARD_MAIL_COMMAND", "/home/flow/gmail-venv/bin/python /home/flow/gmail_api.py send")
        subprocess.run([*sender.split(), email, subject, body], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @staticmethod
    def clean_email(email) -> str:
        return str(email or "").strip().lower()

    @staticmethod
    def hash_code(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()


def init_user_from_cli(auth: AuthManager, argv: list[str]) -> bool:
    if len(argv) >= 4 and argv[1] == "init-user":
        auth.init_db()
        auth.create_or_update_user(argv[2], argv[3], confirmed=True)
        print(f"USER_INITIALIZED {auth.clean_email(argv[2])}")
        return True
    return False
