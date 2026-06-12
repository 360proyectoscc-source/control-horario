# Control Horario

App web sencilla para control horario interno de menos de 10 trabajadores.

## Funciones

- Fichaje de entrada, pausa, reanudacion y salida.
- Geolocalizacion puntual en cada fichaje.
- Login con email y contrasena o modo kiosko con PIN.
- Historial mensual para cada trabajador.
- Solicitudes de correccion del dia.
- Panel administrador para registros, empleados, centros y exportacion CSV.
- SQLite con disco persistente para un cliente pequeno.

## Ejecutar en local

```powershell
python -m control_horario_app.server
```

Abrir:

```text
http://127.0.0.1:8765
```

Administrador inicial si la base esta vacia:

```text
admin@example.com / cambiar123
```

## Tests

```powershell
python -m unittest discover -s control_horario_app/tests -v
```

## Render

El repositorio incluye `render.yaml` para crear el servicio desde Blueprint.

Variables necesarias:

- `SESSION_SECRET`: secreto largo para firmar sesiones.
- `ADMIN_EMAIL`: email del administrador inicial.
- `ADMIN_PASSWORD`: contrasena inicial del administrador.
- `ADMIN_PIN`: PIN inicial del administrador.

Variables ya definidas en el Blueprint:

- `APP_ENV=production`
- `HOST=0.0.0.0`
- `CONTROL_HORARIO_DATA_DIR=/var/data`

El servicio monta un disco persistente de 1 GB en `/var/data`, donde se guarda `control_horario.sqlite3`.
