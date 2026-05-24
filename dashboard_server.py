#!/usr/bin/env python3
import html
import os
import re
import subprocess
import sys
from pathlib import Path

from flask import Flask, redirect, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from auth_core import AuthManager, init_user_from_cli


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "gastos-repository"
UPLOAD_DIR = BASE_DIR / "uploads"
IMPORT_SCRIPT = BASE_DIR / "import_and_generate.sh"

app = Flask(__name__)
auth = AuthManager(BASE_DIR, "Gestión de Gastos")
auth.init_app(app)


def safe_filename(name):
    clean = secure_filename(Path(name or "movements.xls").name)
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", clean).strip("._-")
    return clean or "movements.xls"


@app.get("/")
@auth.require_login
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:path>")
@auth.require_login
def static_files(path):
    return send_from_directory(WEB_DIR, path)


@app.post("/upload")
@auth.require_login
def upload():
    field = request.files.get("movement_file")
    if not field or not field.filename:
        return redirect_result("error", "No se recibió ningún Excel.")

    filename = safe_filename(field.filename)
    suffix = Path(filename).suffix.lower()
    if suffix != ".xls":
        return redirect_result("error", "Formato no válido. Sube el Excel exportado en .xls.")

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
<p><a href="/">Volver al dashboard</a></p>
</main></body></html>"""


def main():
    if init_user_from_cli(auth, sys.argv):
        return
    port = int(os.environ.get("PORT", "8081"))
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()
