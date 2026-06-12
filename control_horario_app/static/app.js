const state = { user: null, today: new Date().toISOString().slice(0, 10) };

const $ = (id) => document.getElementById(id);

function showToast(message) {
  const box = $("toast");
  box.textContent = message;
  box.classList.remove("hidden");
  setTimeout(() => box.classList.add("hidden"), 2600);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(data.error || "Error");
  return data;
}

function setView(name) {
  ["auth-view", "worker-view", "admin-view"].forEach((id) => $(id).classList.add("hidden"));
  $(name).classList.remove("hidden");
}

function fmtHours(value) {
  const total = Math.round((Number(value) || 0) * 60);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function nextActions(summary) {
  if (!summary || summary.state === "sin_iniciar") return [["entrada", "Entrar", "ok"]];
  if (summary.state === "trabajando") return [["pausa", "Pausa", "secondary"], ["salida", "Salir", "danger"]];
  if (summary.state === "en_pausa") return [["reanudacion", "Reanudar", "primary"]];
  return [];
}

async function getLocation() {
  if (!navigator.geolocation) return { geo_status: "no_disponible" };
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({
        lat: pos.coords.latitude,
        lon: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
      }),
      (err) => resolve({ geo_status: err.code === 1 ? "denegada" : "no_disponible" }),
      { enableHighAccuracy: true, timeout: 6000, maximumAge: 30000 }
    );
  });
}

async function recordPunch(eventType) {
  const location = await getLocation();
  const payload = {
    event_type: eventType,
    at: new Date().toISOString().slice(0, 19),
    mode: state.kiosk ? "kiosk" : "mobile",
    ...location,
  };
  await api("/api/punch", { method: "POST", body: JSON.stringify(payload) });
  showToast("Fichaje guardado");
  await loadWorker();
}

function renderWorkerDay(day) {
  $("state-label").textContent = day.state.replace("_", " ");
  $("hours-label").textContent = fmtHours(day.worked_hours);
  const last = day.events[day.events.length - 1];
  $("location-label").textContent = last ? `Ubicacion: ${last.geo_status}` : "Ubicacion pendiente";
  $("action-buttons").innerHTML = nextActions(day).map(([type, label, cls]) =>
    `<button class="${cls}" onclick="recordPunch('${type}')" type="button">${label}</button>`
  ).join("");
  $("today-events").innerHTML = day.events.length ? day.events.map((event) =>
    `<div class="event"><div><strong>${event.event_type}</strong><br><small>${event.geo_status}</small></div><span>${event.happened_at.slice(11,16)}</span></div>`
  ).join("") : `<div class="event"><small>Sin fichajes hoy</small></div>`;
}

async function loadWorker() {
  const month = state.today.slice(0, 7);
  const data = await api(`/api/my-month?month=${month}`);
  const today = data.days.find((item) => item.date === state.today) || { state: "sin_iniciar", worked_hours: 0, events: [] };
  renderWorkerDay(today);
  $("month-history").innerHTML = data.days.length ? data.days.map((day) =>
    `<div class="row"><div><strong>${day.date}</strong><br><small>${day.state}</small></div><span>${fmtHours(day.worked_hours)}</span></div>`
  ).join("") : `<div class="row"><small>Sin registros este mes</small></div>`;
}

async function loadAdmin() {
  const data = await api(`/api/admin/dashboard?date=${state.today}`);
  $("admin-dashboard").innerHTML = data.workers.map((worker) =>
    `<div class="row"><div><strong>${worker.worker_name}</strong><br><small>${worker.last_event_type || "sin fichar"}</small></div><span>${worker.state}</span></div>`
  ).join("") || `<div class="row"><small>Sin trabajadores</small></div>`;
  updateExportLink();
}

async function loadCorrections() {
  const data = await api("/api/admin/corrections");
  $("corrections-list").innerHTML = data.requests.map((req) =>
    `<div class="row"><div><strong>${req.worker_name}</strong><br><small>${req.work_date} · ${req.description}</small></div><button type="button" onclick="approveCorrection('${req.id}')">Aprobar</button></div>`
  ).join("") || `<div class="row"><small>No hay solicitudes</small></div>`;
}

async function approveCorrection(id) {
  const eventAt = prompt("Fecha y hora del evento aprobado (YYYY-MM-DDTHH:MM:SS)");
  const eventType = prompt("Tipo: entrada, pausa, reanudacion o salida", "entrada");
  await api(`/api/admin/corrections/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ approve: true, admin_comment: "Aprobado desde panel", event_type: eventType, event_at: eventAt }),
  });
  showToast("Correccion aprobada");
  await loadCorrections();
  await loadAdmin();
}

function updateExportLink() {
  const month = $("export-month").value || state.today.slice(0, 7);
  $("export-month").value = month;
  $("export-link").href = `/api/admin/export.csv?month=${month}`;
}

async function afterLogin(data, kiosk = false) {
  state.user = data.user;
  state.kiosk = kiosk;
  if (data.user.role === "admin") {
    $("admin-name").textContent = data.user.name;
    setView("admin-view");
    await loadAdmin();
  } else {
    $("worker-name").textContent = data.user.name;
    setView("worker-view");
    await loadWorker();
  }
}

async function logout() {
  await api("/api/logout", { method: "POST", body: "{}" });
  state.user = null;
  setView("auth-view");
}

function bindForms() {
  $("tab-email").onclick = () => {
    $("tab-email").classList.add("active");
    $("tab-kiosk").classList.remove("active");
    $("email-form").classList.remove("hidden");
    $("kiosk-form").classList.add("hidden");
  };
  $("tab-kiosk").onclick = () => {
    $("tab-kiosk").classList.add("active");
    $("tab-email").classList.remove("active");
    $("kiosk-form").classList.remove("hidden");
    $("email-form").classList.add("hidden");
  };
  $("email-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const form = new FormData(ev.currentTarget);
    afterLogin(await api("/api/login", { method: "POST", body: JSON.stringify(Object.fromEntries(form)) }));
  };
  $("kiosk-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const form = new FormData(ev.currentTarget);
    afterLogin(await api("/api/kiosk-login", { method: "POST", body: JSON.stringify(Object.fromEntries(form)) }), true);
  };
  $("logout-worker").onclick = logout;
  $("logout-admin").onclick = logout;
  $("refresh-worker").onclick = loadWorker;
  $("refresh-admin").onclick = loadAdmin;
  $("load-corrections").onclick = loadCorrections;
  $("export-month").onchange = updateExportLink;
  $("correction-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const form = Object.fromEntries(new FormData(ev.currentTarget));
    await api("/api/correction-requests", { method: "POST", body: JSON.stringify(form) });
    ev.currentTarget.reset();
    showToast("Solicitud enviada");
  };
  $("user-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const form = Object.fromEntries(new FormData(ev.currentTarget));
    await api("/api/admin/users", { method: "POST", body: JSON.stringify({ ...form, role: "worker" }) });
    ev.currentTarget.reset();
    showToast("Trabajador creado");
    await loadAdmin();
  };
  $("center-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const form = Object.fromEntries(new FormData(ev.currentTarget));
    await api("/api/admin/centers", { method: "POST", body: JSON.stringify(form) });
    ev.currentTarget.reset();
    showToast("Centro guardado");
  };
}

window.recordPunch = recordPunch;
window.approveCorrection = approveCorrection;
bindForms();
api("/api/me").then((data) => {
  if (data.user) afterLogin({ user: data.user });
}).catch(() => {});
