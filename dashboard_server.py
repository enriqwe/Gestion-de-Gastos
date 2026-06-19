#!/usr/bin/env python3
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename

from auth_core import AuthManager, init_user_from_cli
from categorize_movements import movement_text


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "gastos-repository"
DATA_PATH = WEB_DIR / "movements.json"
CUSTOM_RULES_PATH = BASE_DIR / "category_rules.json"
UPLOAD_DIR = BASE_DIR / "uploads"
IMPORT_SCRIPT = BASE_DIR / "import_and_generate.sh"
GENERATE_SCRIPT = BASE_DIR / "generate_dashboard.py"
SUPPORTED_IMPORT_BANKS = {
    "ing": {
        "label": "ING",
        "extensions": {".xls"},
    },
}

app = Flask(__name__)
auth = AuthManager(BASE_DIR, "Gestión de Gastos")
auth.init_app(app)


def public_dashboard(path: str = "") -> str:
    base = os.environ.get("PUBLIC_DASHBOARD_URL", "https://enriqwe.es/gastos/").rstrip("/") + "/"
    return base + path.lstrip("/")


def can_serve_dashboard():
    trusted_user = request.headers.get("X-OpenClaw-User")
    trusted_local_user = trusted_user and request.remote_addr in {"127.0.0.1", "::1"}
    return bool(trusted_local_user or session.get("user_email"))


def safe_filename(name):
    clean = secure_filename(Path(name or "movements.xls").name)
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", clean).strip("._-")
    return clean or "movements.xls"


@app.get("/")
def index():
    if not can_serve_dashboard():
        return redirect(url_for("login", next=request.path), code=302)
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:path>")
def static_files(path):
    if not can_serve_dashboard():
        return redirect(url_for("login", next=request.path), code=302)
    return send_from_directory(WEB_DIR, path)


@app.post("/upload")
@auth.require_login
def upload():
    field = request.files.get("movement_file")
    if not field or not field.filename:
        return redirect_result("error", "No se recibió ningún Excel.")

    bank = short_text(request.form.get("bank"), 40).lower()
    bank_config = SUPPORTED_IMPORT_BANKS.get(bank)
    if not bank_config:
        return redirect_result("error", "Selecciona el banco antes de subir el fichero. Ahora mismo el importador activo es ING.")

    filename = safe_filename(field.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in bank_config["extensions"]:
        extensions = ", ".join(sorted(bank_config["extensions"]))
        return redirect_result("error", f"Formato no válido para {bank_config['label']}. Sube el fichero exportado en {extensions}.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / filename
    counter = 1
    while destination.exists():
        destination = UPLOAD_DIR / f"{Path(filename).stem}-{counter}{suffix}"
        counter += 1
    field.save(destination)

    try:
        result = subprocess.run(
            [str(IMPORT_SCRIPT), str(destination)],
            cwd=str(BASE_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
    except Exception as exc:
        return redirect_result("error", f"Error ejecutando importación: {exc}")

    if result.returncode == 0:
        return redirect_result("ok", result.stdout.strip() or "Importación completada.")
    return redirect_result(
        "error",
        "No he podido importar ese Excel. Comprueba que sea el .xls original exportado desde el banco y vuelve a intentarlo.",
    )


def redirect_result(status, message):
    from urllib.parse import urlencode

    return redirect("/upload-result?" + urlencode({"status": status, "message": message[-1800:]}), code=303)


def short_text(value, limit=120):
    clean = " ".join(str(value or "").split())
    return clean[:limit].strip()


def movement_kind(movement):
    amount = movement.get("amount", 0) or 0
    if amount > 0:
        return "income"
    if amount < 0:
        return "expense"
    return ""


def load_movements_data():
    if not DATA_PATH.exists():
        raise ValueError("No existe movements.json.")
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def save_movements_data(data):
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_custom_rules():
    if not CUSTOM_RULES_PATH.exists():
        return []
    try:
        rules = json.loads(CUSTOM_RULES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return rules if isinstance(rules, list) else []


def save_custom_rules(rules):
    CUSTOM_RULES_PATH.write_text(json.dumps(rules, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def regenerate_dashboard():
    return subprocess.run(
        [sys.executable, str(GENERATE_SCRIPT)],
        cwd=str(BASE_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )


@app.post("/recategorize")
@app.post("/gastos/recategorize")
@auth.require_login
def recategorize():
    payload = request.get_json(silent=True) or {}
    movement_id = short_text(payload.get("id"), 80)
    category = short_text(payload.get("category"), 80)
    subcategory = short_text(payload.get("subcategory"), 80)
    apply_similar = bool(payload.get("applySimilar", True))

    if not movement_id or not category:
        return jsonify({"ok": False, "error": "Falta movimiento o categoría."}), 400

    try:
        data = load_movements_data()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    movements = data.get("movements", [])
    selected = next((m for m in movements if m.get("id") == movement_id), None)
    if not selected:
        return jsonify({"ok": False, "error": "No encuentro ese movimiento."}), 404

    selected_text = movement_text(selected)
    selected_kind = movement_kind(selected)
    changed = []
    for movement in movements:
        same_rule_target = apply_similar and movement_text(movement) == selected_text and movement_kind(movement) == selected_kind
        if movement.get("id") == movement_id or same_rule_target:
            movement.setdefault("original_category", movement.get("category", ""))
            movement.setdefault("original_subcategory", movement.get("subcategory", ""))
            movement["category"] = category
            movement["subcategory"] = subcategory
            movement["classification_rule"] = "manual_dashboard"
            movement["manual_category"] = True
            movement["recategorized_at"] = datetime.now().isoformat(timespec="seconds")
            changed.append(movement.get("id"))

    save_movements_data(data)

    rule_saved = False
    if apply_similar and selected_text:
        rules = load_custom_rules()
        rule = {
            "category": category,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "kind": selected_kind,
            "name": f"manual_{movement_id}",
            "source_movement_id": movement_id,
            "source_text": short_text(selected.get("description"), 160),
            "subcategory": subcategory,
            "text": selected_text,
        }
        replaced = False
        for idx, existing in enumerate(rules):
            if existing.get("text") == selected_text and existing.get("kind", "") == selected_kind:
                rules[idx] = rule
                replaced = True
                break
        if not replaced:
            rules.append(rule)
        save_custom_rules(rules)
        rule_saved = True

    result = regenerate_dashboard()
    if result.returncode != 0:
        return jsonify({
            "ok": False,
            "error": "Recategorizado guardado, pero no se pudo regenerar el dashboard.",
            "details": result.stdout[-1200:],
        }), 500

    return jsonify({"ok": True, "changed": len(changed), "ruleSaved": rule_saved})


@app.get("/upload-result")
@auth.require_login
def upload_result():
    status = request.args.get("status", "")
    message = request.args.get("message", "")
    title = "Importación completada" if status == "ok" else "Importación con error"
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#080d1a;color:#eef4ff;padding:28px}}
main{{max-width:860px;margin:0 auto;background:#111a2e;border:1px solid #263655;border-radius:18px;padding:22px}}
a{{color:#9cc8ff}}pre{{white-space:pre-wrap;background:#0d1426;border:1px solid #2f3d60;border-radius:12px;padding:14px;overflow:auto}}
.ok{{color:#45d483}}.error{{color:#ff5d73}}
</style></head><body><main>
<h1 class="{html.escape(status)}">{html.escape(title)}</h1>
<pre>{html.escape(message)}</pre>
<p><a href="{html.escape(public_dashboard())}">Volver al dashboard</a></p>
</main></body></html>"""


def main():
    if init_user_from_cli(auth, sys.argv):
        return
    port = int(os.environ.get("PORT", "8081"))
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()
