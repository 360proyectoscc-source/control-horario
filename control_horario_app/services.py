import csv
import io
import json
import math
import uuid
from datetime import datetime, timedelta

from .security import hash_secret, verify_secret
from .storage import connect, init_db, row_to_dict


EVENTS = ("entrada", "pausa", "reanudacion", "salida")
NEXT_ALLOWED = {
    "sin_iniciar": {"entrada"},
    "trabajando": {"pausa", "salida"},
    "en_pausa": {"reanudacion"},
    "finalizado": set(),
}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def new_id(prefix):
    return "{}_{}".format(prefix, uuid.uuid4().hex[:12])


def parse_dt(value):
    return datetime.fromisoformat(value)


def haversine_meters(lat1, lon1, lat2, lon2):
    radius = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class TimeClockService:
    def __init__(self, db_path=None):
        self.db_path = db_path
        init_db(db_path)

    def _conn(self):
        return connect(self.db_path)

    def create_user(self, name, email, password, pin, role="worker", weekly_hours=40):
        user = {
            "id": new_id("usr"),
            "name": name.strip(),
            "email": email.strip().lower() if email else None,
            "password_hash": hash_secret(password) if password else None,
            "pin_hash": hash_secret(pin) if pin else None,
            "role": role,
            "weekly_hours": float(weekly_hours),
            "active": True,
            "created_at": now_iso(),
        }
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO users(id, name, email, password_hash, pin_hash, role, weekly_hours, active, created_at)
                VALUES (:id, :name, :email, :password_hash, :pin_hash, :role, :weekly_hours, :active, :created_at)
                """,
                {**user, "active": 1},
            )
        return user

    def list_users(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY role, name").fetchall()
        return [row_to_dict(row) for row in rows]

    def get_user(self, user_id):
        with self._conn() as conn:
            return row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def authenticate_email(self, email, password):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE lower(email) = lower(?) AND active = 1",
                (email.strip(),),
            ).fetchone()
        user = row_to_dict(row)
        if user and user["password_hash"] and verify_secret(password, user["password_hash"]):
            return user
        return None

    def authenticate_pin(self, pin):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM users WHERE active = 1 AND pin_hash IS NOT NULL").fetchall()
        for row in rows:
            user = row_to_dict(row)
            if verify_secret(pin, user["pin_hash"]):
                return user
        return None

    def create_center(self, name, address, lat, lon, radius_meters):
        center = {
            "id": new_id("ctr"),
            "name": name.strip(),
            "address": address.strip(),
            "lat": float(lat),
            "lon": float(lon),
            "radius_meters": float(radius_meters),
            "active": True,
        }
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO centers(id, name, address, lat, lon, radius_meters, active)
                VALUES (:id, :name, :address, :lat, :lon, :radius_meters, 1)
                """,
                center,
            )
        return center

    def list_centers(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM centers ORDER BY name").fetchall()
        return [row_to_dict(row) for row in rows]

    def events_for_day(self, worker_id, date_text):
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE worker_id = ? AND substr(happened_at, 1, 10) = ?
                ORDER BY happened_at, created_at
                """,
                (worker_id, date_text),
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def current_state(self, worker_id, date_text):
        events = self.events_for_day(worker_id, date_text)
        if not events:
            return "sin_iniciar"
        last = events[-1]["event_type"]
        return {
            "entrada": "trabajando",
            "reanudacion": "trabajando",
            "pausa": "en_pausa",
            "salida": "finalizado",
        }[last]

    def record_punch(
        self,
        worker_id,
        event_type,
        *,
        at=None,
        mode="mobile",
        lat=None,
        lon=None,
        accuracy=None,
        geo_status=None,
        note=None,
        allow_any_sequence=False,
    ):
        if event_type not in EVENTS:
            raise ValueError("Tipo de fichaje no valido")
        at = at or now_iso()
        state = self.current_state(worker_id, at[:10])
        if not allow_any_sequence and event_type not in NEXT_ALLOWED[state]:
            raise ValueError("Secuencia de fichaje no permitida")

        geo = self._geolocate(lat, lon, geo_status)
        event = {
            "id": new_id("evt"),
            "worker_id": worker_id,
            "event_type": event_type,
            "happened_at": at,
            "mode": mode,
            "lat": lat,
            "lon": lon,
            "accuracy_meters": accuracy,
            "geo_status": geo["geo_status"],
            "center_id": geo["center_id"],
            "distance_meters": geo["distance_meters"],
            "inside_radius": geo["inside_radius"],
            "note": note,
            "created_at": now_iso(),
        }
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO events(
                    id, worker_id, event_type, happened_at, mode, lat, lon, accuracy_meters,
                    geo_status, center_id, distance_meters, inside_radius, note, created_at
                )
                VALUES (
                    :id, :worker_id, :event_type, :happened_at, :mode, :lat, :lon, :accuracy_meters,
                    :geo_status, :center_id, :distance_meters, :inside_radius, :note, :created_at
                )
                """,
                {**event, "inside_radius": None if event["inside_radius"] is None else int(event["inside_radius"])},
            )
        return event

    def _geolocate(self, lat, lon, explicit_status):
        if lat is None or lon is None:
            return {
                "geo_status": explicit_status or "no_disponible",
                "center_id": None,
                "distance_meters": None,
                "inside_radius": None,
            }
        centers = self.list_centers()
        if not centers:
            return {
                "geo_status": explicit_status or "confirmada",
                "center_id": None,
                "distance_meters": None,
                "inside_radius": None,
            }
        nearest = min(centers, key=lambda c: haversine_meters(float(lat), float(lon), c["lat"], c["lon"]))
        distance = haversine_meters(float(lat), float(lon), nearest["lat"], nearest["lon"])
        inside = distance <= nearest["radius_meters"]
        return {
            "geo_status": "confirmada" if inside else "fuera_de_zona",
            "center_id": nearest["id"],
            "distance_meters": round(distance, 1),
            "inside_radius": inside,
        }

    def day_summary(self, worker_id, date_text):
        events = self.events_for_day(worker_id, date_text)
        worked = 0.0
        start = None
        for event in events:
            happened = parse_dt(event["happened_at"])
            if event["event_type"] in ("entrada", "reanudacion"):
                start = happened
            elif event["event_type"] in ("pausa", "salida") and start:
                worked += (happened - start).total_seconds() / 3600
                start = None
        return {
            "date": date_text,
            "state": self.current_state(worker_id, date_text),
            "worked_hours": round(worked, 2),
            "events": events,
        }

    def month_history(self, worker_id, month):
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT substr(happened_at, 1, 10) AS day
                FROM events
                WHERE worker_id = ? AND substr(happened_at, 1, 7) = ?
                ORDER BY day
                """,
                (worker_id, month),
            ).fetchall()
        return [self.day_summary(worker_id, row["day"]) for row in rows]

    def request_correction(self, worker_id, date_text, description, reason):
        request = {
            "id": new_id("cor"),
            "worker_id": worker_id,
            "work_date": date_text,
            "description": description.strip(),
            "reason": reason.strip(),
            "status": "pendiente",
            "admin_comment": None,
            "created_at": now_iso(),
            "resolved_at": None,
            "resolved_by": None,
        }
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO correction_requests(
                    id, worker_id, work_date, description, reason, status, admin_comment,
                    created_at, resolved_at, resolved_by
                )
                VALUES (
                    :id, :worker_id, :work_date, :description, :reason, :status, :admin_comment,
                    :created_at, :resolved_at, :resolved_by
                )
                """,
                request,
            )
        return request

    def list_corrections(self, status=None):
        sql = """
            SELECT cr.*, u.name AS worker_name
            FROM correction_requests cr JOIN users u ON u.id = cr.worker_id
        """
        params = ()
        if status:
            sql += " WHERE cr.status = ?"
            params = (status,)
        sql += " ORDER BY cr.created_at DESC"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]

    def resolve_correction(
        self,
        request_id,
        admin_id,
        *,
        approve,
        admin_comment,
        event_type=None,
        event_at=None,
    ):
        with self._conn() as conn:
            before = row_to_dict(conn.execute("SELECT * FROM correction_requests WHERE id = ?", (request_id,)).fetchone())
        if not before:
            raise ValueError("Solicitud no encontrada")
        status = "aprobada" if approve else "rechazada"
        event = None
        if approve and event_type and event_at:
            event = self.record_punch(
                before["worker_id"],
                event_type,
                at=event_at,
                mode="admin",
                geo_status="no_disponible",
                allow_any_sequence=True,
            )
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE correction_requests
                SET status = ?, admin_comment = ?, resolved_at = ?, resolved_by = ?
                WHERE id = ?
                """,
                (status, admin_comment, now_iso(), admin_id, request_id),
            )
            after = row_to_dict(conn.execute("SELECT * FROM correction_requests WHERE id = ?", (request_id,)).fetchone())
            conn.execute(
                """
                INSERT INTO audit_log(id, actor_id, action, entity, entity_id, before_data, after_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("aud"),
                    admin_id,
                    "approve_correction" if approve else "reject_correction",
                    "correction_request",
                    request_id,
                    json.dumps(before, ensure_ascii=False),
                    json.dumps({"request": after, "event": event}, ensure_ascii=False),
                    now_iso(),
                ),
            )
        return after

    def audit_entries(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY created_at, id").fetchall()
        return [row_to_dict(row) for row in rows]

    def admin_dashboard(self, date_text):
        workers = [u for u in self.list_users() if u["role"] == "worker" and u["active"]]
        rows = []
        for worker in workers:
            summary = self.day_summary(worker["id"], date_text)
            last = summary["events"][-1] if summary["events"] else None
            rows.append(
                {
                    "worker_id": worker["id"],
                    "worker_name": worker["name"],
                    "state": summary["state"],
                    "worked_hours": summary["worked_hours"],
                    "last_event_type": last["event_type"] if last else None,
                    "last_event_at": last["happened_at"] if last else None,
                }
            )
        return rows

    def export_month_csv(self, month):
        workers = {u["id"]: u for u in self.list_users()}
        with self._conn() as conn:
            days = conn.execute(
                """
                SELECT DISTINCT worker_id, substr(happened_at, 1, 10) AS day
                FROM events
                WHERE substr(happened_at, 1, 7) = ?
                ORDER BY day, worker_id
                """,
                (month,),
            ).fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Trabajador", "Fecha", "Estado", "Horas trabajadas", "Eventos", "Incidencias"])
        for row in days:
            summary = self.day_summary(row["worker_id"], row["day"])
            events = " | ".join("{} {}".format(e["event_type"], e["happened_at"][11:16]) for e in summary["events"])
            incidents = " | ".join(e["geo_status"] for e in summary["events"] if e["geo_status"] != "confirmada")
            writer.writerow(
                [
                    workers[row["worker_id"]]["name"],
                    row["day"],
                    summary["state"],
                    summary["worked_hours"],
                    events,
                    incidents,
                ]
            )
        return output.getvalue()
