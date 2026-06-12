import json
import os
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .emailer import send_admin_correction_notice
from .security import sign_token, verify_token
from .services import TimeClockService
from .storage import default_db_path, init_db


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
SESSION_COOKIE = "control_horario_session"


def json_dumps(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class TimeClockServer(ThreadingHTTPServer):
    def __init__(self, server_address, db_path=None, session_secret=None):
        super().__init__(server_address, Handler)
        self.db_path = Path(db_path or default_db_path())
        self.session_secret = session_secret or os.getenv("SESSION_SECRET", "dev-secret-change-me")
        init_db(self.db_path)

    @property
    def service(self):
        return TimeClockService(self.db_path)


def create_server(server_address=("0.0.0.0", 8765), db_path=None, session_secret=None):
    return TimeClockServer(server_address, db_path=db_path, session_secret=session_secret)


class Handler(BaseHTTPRequestHandler):
    server_version = "ControlHorario/0.1"

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            return self.json({"ok": True, "db_path": str(self.server.db_path)})
        if parsed.path == "/api/me":
            user = self.current_user()
            return self.json({"ok": bool(user), "user": self.public_user(user) if user else None})
        if parsed.path == "/api/my-month":
            user = self.require_user()
            if not user:
                return
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            return self.json({"ok": True, "days": self.server.service.month_history(user["id"], month)})
        if parsed.path == "/api/admin/dashboard":
            admin = self.require_admin()
            if not admin:
                return
            date_text = query.get("date", [datetime.now().date().isoformat()])[0]
            return self.json({"ok": True, "workers": self.server.service.admin_dashboard(date_text)})
        if parsed.path == "/api/admin/users":
            admin = self.require_admin()
            if not admin:
                return
            return self.json({"ok": True, "users": [self.public_user(u) for u in self.server.service.list_users()]})
        if parsed.path == "/api/admin/centers":
            admin = self.require_admin()
            if not admin:
                return
            return self.json({"ok": True, "centers": self.server.service.list_centers()})
        if parsed.path == "/api/admin/corrections":
            admin = self.require_admin()
            if not admin:
                return
            return self.json({"ok": True, "requests": self.server.service.list_corrections()})
        if parsed.path == "/api/admin/export.csv":
            admin = self.require_admin()
            if not admin:
                return
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            return self.text(self.server.service.export_month_csv(month), "text/csv; charset=utf-8")
        if parsed.path == "/" or parsed.path == "/index.html":
            return self.static_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if parsed.path.startswith("/static/"):
            return self.static_file(STATIC_DIR / Path(parsed.path).name, self.content_type(parsed.path))
        return self.error_json(HTTPStatus.NOT_FOUND, "No encontrado")

    def do_POST(self):
        parsed = urlparse(self.path)
        payload = self.read_json()
        if parsed.path == "/api/login":
            user = self.server.service.authenticate_email(payload.get("email", ""), payload.get("password", ""))
            if not user:
                return self.error_json(HTTPStatus.UNAUTHORIZED, "Credenciales incorrectas")
            return self.auth_response(user)
        if parsed.path == "/api/kiosk-login":
            user = self.server.service.authenticate_pin(str(payload.get("pin", "")))
            if not user:
                return self.error_json(HTTPStatus.UNAUTHORIZED, "PIN incorrecto")
            return self.auth_response(user)
        if parsed.path == "/api/logout":
            return self.json({"ok": True}, headers={"Set-Cookie": self.clear_cookie()})
        if parsed.path == "/api/punch":
            user = self.require_user()
            if not user:
                return
            try:
                event = self.server.service.record_punch(
                    user["id"],
                    payload.get("event_type", ""),
                    at=payload.get("at"),
                    mode=payload.get("mode", "mobile"),
                    lat=payload.get("lat"),
                    lon=payload.get("lon"),
                    accuracy=payload.get("accuracy"),
                    geo_status=payload.get("geo_status"),
                    note=payload.get("note"),
                )
            except ValueError as exc:
                return self.error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return self.json({"ok": True, "event": event, "summary": self.server.service.day_summary(user["id"], event["happened_at"][:10])})
        if parsed.path == "/api/correction-requests":
            user = self.require_user()
            if not user:
                return
            req = self.server.service.request_correction(
                user["id"],
                payload.get("date", datetime.now().date().isoformat()),
                payload.get("description", ""),
                payload.get("reason", ""),
            )
            send_admin_correction_notice(user["name"], req["description"])
            return self.json({"ok": True, "request": req})
        if parsed.path == "/api/admin/users":
            admin = self.require_admin()
            if not admin:
                return
            user = self.server.service.create_user(
                payload.get("name", ""),
                payload.get("email", ""),
                payload.get("password", "cambiar123"),
                payload.get("pin", ""),
                payload.get("role", "worker"),
                payload.get("weekly_hours", 40),
            )
            return self.json({"ok": True, "user": self.public_user(user)})
        if parsed.path == "/api/admin/centers":
            admin = self.require_admin()
            if not admin:
                return
            center = self.server.service.create_center(
                payload.get("name", ""),
                payload.get("address", ""),
                payload.get("lat"),
                payload.get("lon"),
                payload.get("radius_meters", 100),
            )
            return self.json({"ok": True, "center": center})
        if parsed.path.startswith("/api/admin/corrections/") and parsed.path.endswith("/approve"):
            admin = self.require_admin()
            if not admin:
                return
            request_id = parsed.path.split("/")[-2]
            try:
                req = self.server.service.resolve_correction(
                    request_id,
                    admin["id"],
                    approve=bool(payload.get("approve", True)),
                    admin_comment=payload.get("admin_comment", ""),
                    event_type=payload.get("event_type"),
                    event_at=payload.get("event_at"),
                )
            except ValueError as exc:
                return self.error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return self.json({"ok": True, "request": req})
        return self.error_json(HTTPStatus.NOT_FOUND, "No encontrado")

    def log_message(self, fmt, *args):
        return

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def json(self, payload, status=HTTPStatus.OK, headers=None):
        data = json_dumps(payload)
        self.send_response(status)
        self._cors()
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def text(self, payload, content_type):
        data = payload.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def static_file(self, path, content_type):
        if not path.exists() or not path.is_file():
            return self.error_json(HTTPStatus.NOT_FOUND, "Archivo no encontrado")
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def error_json(self, status, message):
        return self.json({"ok": False, "error": message}, status=status)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def auth_response(self, user):
        return self.json(
            {"ok": True, "user": self.public_user(user)},
            headers={"Set-Cookie": self.session_cookie(user["id"])},
        )

    def cookie_map(self):
        cookies = {}
        for item in self.headers.get("Cookie", "").split(";"):
            if "=" in item:
                key, value = item.split("=", 1)
                cookies[key.strip()] = value.strip()
        return cookies

    def current_user(self):
        token = self.cookie_map().get(SESSION_COOKIE)
        user_id = verify_token(token, self.server.session_secret) if token else None
        return self.server.service.get_user(user_id) if user_id else None

    def require_user(self):
        user = self.current_user()
        if not user:
            self.error_json(HTTPStatus.UNAUTHORIZED, "Acceso no autorizado")
            return None
        return user

    def require_admin(self):
        user = self.require_user()
        if not user:
            return None
        if user["role"] != "admin":
            self.error_json(HTTPStatus.FORBIDDEN, "Solo administradores")
            return None
        return user

    def session_cookie(self, user_id):
        parts = [
            "{}={}".format(SESSION_COOKIE, sign_token(user_id, self.server.session_secret)),
            "HttpOnly",
            "Path=/",
            "SameSite=Lax",
            "Max-Age=43200",
        ]
        if os.getenv("APP_ENV", "").lower() in {"prod", "production", "render"}:
            parts.append("Secure")
        return "; ".join(parts)

    def clear_cookie(self):
        return "{}=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0".format(SESSION_COOKIE)

    def public_user(self, user):
        if not user:
            return None
        return {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "weekly_hours": user["weekly_hours"],
            "active": user["active"],
        }

    def content_type(self, path):
        if path.endswith(".css"):
            return "text/css; charset=utf-8"
        if path.endswith(".js"):
            return "application/javascript; charset=utf-8"
        return "application/octet-stream"


def seed_admin_if_empty(service):
    if service.list_users():
        return
    email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    password = os.getenv("ADMIN_PASSWORD", "cambiar123")
    pin = os.getenv("ADMIN_PIN", "9001")
    service.create_user("Administrador", email, password, pin, "admin", 40)
    print("Admin inicial: {} / {}".format(email, password))


def main():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8765"))
    db_path = os.getenv("CONTROL_HORARIO_DB", str(default_db_path()))
    server = create_server((host, port), db_path)
    seed_admin_if_empty(server.service)
    print("Control horario disponible en http://{}:{}".format(host, port))
    print("Base de datos: {}".format(server.db_path))
    server.serve_forever()


if __name__ == "__main__":
    main()
