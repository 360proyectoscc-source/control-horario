import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from control_horario_app.server import create_server
from control_horario_app.services import TimeClockService
from control_horario_app.storage import init_db


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "api.sqlite3"
        init_db(self.db_path)
        service = TimeClockService(self.db_path)
        self.admin = service.create_user("Admin", "admin@example.com", "adminpass", "9001", "admin", 40)
        self.worker = service.create_user("Ana", "ana@example.com", "secret123", "1234", "worker", 30)
        self.server = create_server(("127.0.0.1", 0), self.db_path, session_secret="test-secret")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:{}".format(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def request(self, method, path, payload=None, cookie=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(self.base + path, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        if cookie:
            req.add_header("Cookie", cookie)
        with urlopen(req, timeout=5) as res:
            data = res.read()
            headers = dict(res.headers.items())
            ctype = headers.get("Content-Type", "")
            if "application/json" in ctype:
                return res.status, headers, json.loads(data.decode("utf-8"))
            return res.status, headers, data.decode("utf-8")

    def login(self, email="ana@example.com", password="secret123"):
        status, headers, data = self.request("POST", "/api/login", {"email": email, "password": password})
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0], data

    def admin_login(self):
        return self.login("admin@example.com", "adminpass")[0]

    def test_worker_login_kiosk_login_and_punch(self):
        cookie, data = self.login()
        self.assertEqual(data["user"]["role"], "worker")
        status, _, kiosk = self.request("POST", "/api/kiosk-login", {"pin": "1234"})
        self.assertEqual(status, 200)
        self.assertEqual(kiosk["user"]["name"], "Ana")
        status, _, punch = self.request(
            "POST",
            "/api/punch",
            {
                "event_type": "entrada",
                "at": "2026-06-12T08:00:00",
                "mode": "mobile",
                "geo_status": "denegada",
            },
            cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(punch["event"]["event_type"], "entrada")
        status, _, month = self.request("GET", "/api/my-month?month=2026-06", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(month["days"][0]["state"], "trabajando")

    def test_correction_request_admin_approval_and_export(self):
        worker_cookie, _ = self.login()
        admin_cookie = self.admin_login()
        status, _, created = self.request(
            "POST",
            "/api/correction-requests",
            {
                "date": "2026-06-12",
                "description": "Olvide entrada",
                "reason": "Error manual",
            },
            worker_cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(created["request"]["status"], "pendiente")
        status, _, approved = self.request(
            "POST",
            "/api/admin/corrections/{}/approve".format(created["request"]["id"]),
            {
                "approve": True,
                "admin_comment": "OK",
                "event_type": "entrada",
                "event_at": "2026-06-12T08:00:00",
            },
            admin_cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(approved["request"]["status"], "aprobada")
        status, headers, csv_text = self.request("GET", "/api/admin/export.csv?month=2026-06", cookie=admin_cookie)
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers["Content-Type"])
        self.assertIn("Trabajador,Fecha", csv_text)

    def test_worker_cannot_call_admin_dashboard(self):
        cookie, _ = self.login()
        try:
            self.request("GET", "/api/admin/dashboard?date=2026-06-12", cookie=cookie)
            self.fail("worker accessed admin dashboard")
        except HTTPError as exc:
            exc.read()
            exc.close()
            self.assertEqual(exc.code, 403)

    def test_static_assets_are_served(self):
        status, headers, html = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Control horario", html)
        status, headers, css = self.request("GET", "/static/styles.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers["Content-Type"])
        self.assertIn("--ink", css)
        status, headers, js = self.request("GET", "/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("application/javascript", headers["Content-Type"])
        self.assertIn("recordPunch", js)

    def test_health_endpoint_reports_database_path(self):
        status, _, data = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("api.sqlite3", data["db_path"])


if __name__ == "__main__":
    unittest.main()
