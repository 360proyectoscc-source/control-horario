import os
import smtplib
from email.message import EmailMessage


def send_admin_correction_notice(worker_name, description):
    to_addr = os.getenv("ADMIN_EMAIL", "").strip()
    host = os.getenv("SMTP_HOST", "").strip()
    if not to_addr or not host:
        print("Correction request pending: {} - {}".format(worker_name, description))
        return False

    msg = EmailMessage()
    msg["Subject"] = "Solicitud de correccion de fichaje"
    msg["From"] = os.getenv("SMTP_FROM", to_addr)
    msg["To"] = to_addr
    msg.set_content("{} ha solicitado una correccion:\n\n{}".format(worker_name, description))

    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(msg)
    return True

