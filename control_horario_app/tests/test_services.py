import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from control_horario_app.security import verify_secret
from control_horario_app.services import TimeClockService
from control_horario_app.storage import init_db


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.sqlite3"
        init_db(self.db_path)
        self.service = TimeClockService(self.db_path)
        self.admin = self.service.create_user(
            name="Admin",
            email="admin@example.com",
            password="adminpass",
            pin="9001",
            role="admin",
            weekly_hours=40,
        )
        self.worker = self.service.create_user(
            name="Ana",
            email="ana@example.com",
            password="secret123",
            pin="1234",
            role="worker",
            weekly_hours=30,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_password_and_pin_are_hashed_and_verified(self):
        user = self.service.authenticate_email("ana@example.com", "secret123")
        self.assertEqual(user["id"], self.worker["id"])
        self.assertTrue(verify_secret("1234", self.worker["pin_hash"]))
        self.assertIsNone(self.service.authenticate_email("ana@example.com", "bad"))
        self.assertEqual(self.service.authenticate_pin("1234")["email"], "ana@example.com")

    def test_punch_sequence_and_pause_aware_totals(self):
        self.service.record_punch(self.worker["id"], "entrada", at="2026-06-12T08:00:00", mode="mobile")
        self.service.record_punch(self.worker["id"], "pausa", at="2026-06-12T10:00:00", mode="mobile")
        self.service.record_punch(self.worker["id"], "reanudacion", at="2026-06-12T10:30:00", mode="mobile")
        self.service.record_punch(self.worker["id"], "salida", at="2026-06-12T13:00:00", mode="mobile")
        summary = self.service.day_summary(self.worker["id"], "2026-06-12")
        self.assertEqual(summary["state"], "finalizado")
        self.assertAlmostEqual(summary["worked_hours"], 4.5)
        with self.assertRaises(ValueError):
            self.service.record_punch(self.worker["id"], "salida", at="2026-06-12T14:00:00", mode="mobile")

    def test_geofence_marks_inside_and_outside_center(self):
        center = self.service.create_center("Oficina", "Calle Mayor 1", 43.3623, -8.4115, 100)
        inside = self.service.record_punch(
            self.worker["id"],
            "entrada",
            at="2026-06-13T08:00:00",
            mode="mobile",
            lat=43.36231,
            lon=-8.41149,
            accuracy=12,
        )
        self.assertEqual(inside["center_id"], center["id"])
        self.assertTrue(inside["inside_radius"])
        self.assertEqual(inside["geo_status"], "confirmada")
        self.service.record_punch(self.worker["id"], "salida", at="2026-06-13T09:00:00", mode="mobile")
        outside = self.service.record_punch(
            self.worker["id"],
            "entrada",
            at="2026-06-14T08:00:00",
            mode="mobile",
            lat=43.38,
            lon=-8.42,
            accuracy=12,
        )
        self.assertEqual(outside["geo_status"], "fuera_de_zona")
        self.assertFalse(outside["inside_radius"])

    def test_missing_location_keeps_punch_with_incident(self):
        event = self.service.record_punch(
            self.worker["id"],
            "entrada",
            at="2026-06-15T08:00:00",
            mode="mobile",
            geo_status="denegada",
        )
        self.assertEqual(event["geo_status"], "denegada")
        self.assertIsNone(event["lat"])

    def test_correction_request_approval_creates_event_and_audit(self):
        request = self.service.request_correction(
            self.worker["id"],
            "2026-06-16",
            "Olvide fichar salida a las 14:00",
            "Salida no registrada",
        )
        self.assertEqual(request["status"], "pendiente")
        approved = self.service.resolve_correction(
            request["id"],
            self.admin["id"],
            approve=True,
            admin_comment="Aprobado",
            event_type="salida",
            event_at="2026-06-16T14:00:00",
        )
        self.assertEqual(approved["status"], "aprobada")
        audit = self.service.audit_entries()
        self.assertEqual(audit[-1]["action"], "approve_correction")

    def test_admin_dashboard_reports_current_states(self):
        self.service.record_punch(self.worker["id"], "entrada", at="2026-06-17T08:00:00", mode="kiosk")
        dashboard = self.service.admin_dashboard("2026-06-17")
        row = next(item for item in dashboard if item["worker_id"] == self.worker["id"])
        self.assertEqual(row["state"], "trabajando")
        self.assertEqual(row["last_event_type"], "entrada")


if __name__ == "__main__":
    unittest.main()
