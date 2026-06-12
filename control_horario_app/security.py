import base64
import hashlib
import hmac
import secrets
import time


def hash_secret(secret, *, salt=None):
    if not secret:
        raise ValueError("secret is required")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, 120_000)
    return "pbkdf2_sha256$120000${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_secret(secret, encoded):
    try:
        algo, rounds, salt_b64, digest_b64 = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def sign_token(payload, secret, ttl_seconds=43_200):
    expires = int(time.time()) + ttl_seconds
    body = "{}|{}".format(payload, expires).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    raw = body + b"|" + sig.encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def verify_token(token, secret):
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        payload, expires, sig = raw.rsplit("|", 2)
        body = "{}|{}".format(payload, expires).encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(expires) < int(time.time()):
            return None
        return payload
    except Exception:
        return None

