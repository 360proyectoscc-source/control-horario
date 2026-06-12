# Control Horario

App web sencilla para control horario interno de menos de 10 trabajadores.

## Funciones

- Login de trabajador con email y contrasena.
- Modo kiosko con PIN personal.
- Fichajes de entrada, pausa, reanudacion y salida.
- Geolocalizacion puntual no bloqueante.
- Centros con radio permitido.
- Historial mensual propio para trabajador.
- Solicitudes de correccion con aprobacion de administrador.
- Dashboard administrador.
- Alta de trabajadores y centros.
- Exportacion mensual CSV compatible con Excel.

## Arranque local

Desde la raiz del workspace:

```powershell
python -m control_horario_app.server
```

Despues abre:

```text
http://127.0.0.1:8765
```

Si la base esta vacia, se crea un administrador inicial:

```text
admin@example.com / cambiar123
```

Puedes cambiarlo con variables de entorno antes de arrancar:

```powershell
$env:ADMIN_EMAIL = "admin@cliente.com"
$env:ADMIN_PASSWORD = "una-clave-segura"
$env:ADMIN_PIN = "9001"
python -m control_horario_app.server
```

## Variables de entorno

- `PORT`: puerto asignado por Render.
- `HOST`: host de escucha. Por defecto `0.0.0.0`.
- `CONTROL_HORARIO_DATA_DIR`: carpeta persistente para la base SQLite.
- `CONTROL_HORARIO_DB`: ruta completa de la base SQLite.
- `SESSION_SECRET`: secreto largo para firmar sesiones.
- `ADMIN_EMAIL`: email del administrador inicial y destino de avisos si no se define otro.
- `ADMIN_PASSWORD`: contrasena del administrador inicial.
- `ADMIN_PIN`: PIN del administrador inicial.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`: envio real de emails.

Si no configuras SMTP, las solicitudes de correccion se registran y se imprime un aviso en logs.

## Render

Configuracion recomendada:

1. Crear un Blueprint en Render conectado al repositorio.
2. Start command: `python -m control_horario_app.server`.
3. Crear un disco persistente y montarlo en `/var/data`.
4. Definir `CONTROL_HORARIO_DATA_DIR=/var/data`.
5. Definir `SESSION_SECRET` con un valor largo y aleatorio.
6. Definir `ADMIN_EMAIL`, `ADMIN_PASSWORD` y `ADMIN_PIN`.
7. Usar el dominio gratuito de Render o configurar un dominio propio mas adelante.

La base por defecto quedara en:

```text
/var/data/control_horario.sqlite3
```

## Tests

```powershell
python -m unittest discover -s control_horario_app/tests -v
```

## Notas de alcance

Este MVP usa SQLite con volumen persistente. Es adecuado para un cliente pequeno con uso interno. Para muchos clientes o mas concurrencia, la ruta natural es migrar a PostgreSQL y separar cada cliente o construir una plataforma multi-cliente.
