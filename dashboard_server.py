#!/usr/bin/env python3
import html
import os
import re
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cgi


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "gastos-repository"
UPLOAD_DIR = BASE_DIR / "uploads"
IMPORT_SCRIPT = BASE_DIR / "import_and_generate.sh"


def safe_filename(name):
    clean = Path(name or "movements.xls").name
    clean = re.sub(r"[^A-Za-z0-9._ -]+", "_", clean).strip(" .")
    return clean or "movements.xls"


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/upload-result":
            self.render_upload_result(parse_qs(parsed.query))
            return
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/upload":
            self.send_error(404, "Ruta no encontrada")
            return
        self.handle_upload()

    def handle_upload(self):
        content_type = self.headers.get("content-type", "")
        if not content_type.startswith("multipart/form-data"):
            self.send_error(400, "La subida debe usar multipart/form-data")
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": self.headers.get("content-length", "0"),
            },
        )
        field = form["movement_file"] if "movement_file" in form else None
        if field is None or not getattr(field, "filename", ""):
            self.redirect_result("error", "No se recibió ningún Excel.")
            return

        filename = safe_filename(field.filename)
        suffix = Path(filename).suffix.lower()
        if suffix != ".xls":
            self.redirect_result("error", "Formato no válido. Sube el Excel exportado en .xls.")
            return

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        destination = UPLOAD_DIR / filename
        counter = 1
        while destination.exists():
            destination = UPLOAD_DIR / f"{Path(filename).stem}-{counter}{suffix}"
            counter += 1

        with destination.open("wb") as out:
            while True:
                chunk = field.file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)

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
            self.redirect_result("error", f"Error ejecutando importación: {exc}")
            return

        if result.returncode == 0:
            status = "ok"
            message = result.stdout.strip() or "Importación completada."
        else:
            status = "error"
            message = (
                "No he podido importar ese Excel. Comprueba que sea el .xls original "
                "exportado desde el banco y vuelve a intentarlo."
            )
        self.redirect_result(status, message)

    def redirect_result(self, status, message):
        from urllib.parse import urlencode

        location = "/upload-result?" + urlencode({"status": status, "message": message[-1800:]})
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def render_upload_result(self, query):
        status = (query.get("status") or [""])[0]
        message = (query.get("message") or [""])[0]
        title = "Importación completada" if status == "ok" else "Importación con error"
        body = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#080d1a;color:#eef4ff;padding:28px}}
main{{max-width:860px;margin:0 auto;background:#111a2e;border:1px solid #263655;border-radius:18px;padding:22px}}
a{{color:#9cc8ff}}pre{{white-space:pre-wrap;background:#0d1426;border:1px solid #2f3d60;border-radius:12px;padding:14px;overflow:auto}}
.ok{{color:#45d483}}.error{{color:#ff5d73}}
</style>
</head>
<body>
<main>
<h1 class="{html.escape(status)}">{html.escape(title)}</h1>
<pre>{html.escape(message)}</pre>
<p><a href="/">Volver al dashboard</a></p>
</main>
</body>
</html>"""
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main():
    port = int(os.environ.get("PORT", "8081"))
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"DASHBOARD_SERVER_OK http://127.0.0.1:{port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
