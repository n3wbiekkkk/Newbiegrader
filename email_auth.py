"""Stateless email proof through Supabase Auth; never mutate the DB client.

Only the verified subject is returned. Provider access/refresh tokens and error
bodies must never enter application cookies, responses, or logs.
"""
import json
import re
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class Unavailable(Exception):
    pass


class RateLimited(Unavailable):
    def __init__(self, retry_after=60):
        try:
            self.retry_after = max(1, min(3600, int(retry_after)))
        except (ValueError, TypeError):
            self.retry_after = 60
        super().__init__('provider rate limited')


class InvalidCode(Exception):
    pass


def normalize_email(value):
    if not isinstance(value, str):
        raise ValueError("bad email")
    email = value.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email, re.ASCII) \
            or not email.isascii():
        raise ValueError("bad email")
    return email


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(url, key, path, body, *, verify=False):
    parsed = urlsplit(url)
    if not key or parsed.scheme != "https" or not parsed.hostname or parsed.username \
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise Unavailable()
    request = Request(url.rstrip("/") + "/auth/v1/" + path,
                      data=json.dumps(body).encode(), method="POST",
                      headers={"apikey": key, "Content-Type": "application/json"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(131073)
            if len(raw) > 131072:
                raise Unavailable()
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise Unavailable()
            return result
    except HTTPError as exc:
        if exc.code == 429:
            retry_after = exc.headers.get('Retry-After', '60') if exc.headers else '60'
            exc.close()
            raise RateLimited(retry_after) from None
        exc.close()
        if verify and exc.code in (400, 401, 403, 422):
            raise InvalidCode() from None
        raise Unavailable() from None
    except (InvalidCode, Unavailable):
        raise
    except Exception:
        raise Unavailable() from None


def request_code(url, key, email):
    _post(url, key, "otp", {"email": email, "create_user": True})


def verify_code(url, key, email, token):
    result = _post(url, key, "verify", {"email": email, "token": token, "type": "email"},
                   verify=True)
    user = result.get("user") or {}
    try:
        subject = str(uuid.UUID(user["id"]))
        if normalize_email(user["email"]) != email or not user.get("email_confirmed_at"):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise InvalidCode() from None
    return subject


def delete_identity(url, key, subject):
    """Hard-delete a previously verified Auth subject; 404 is idempotent."""
    try:
        subject = str(uuid.UUID(subject))
        parsed = urlsplit(url)
        if not key or parsed.scheme != "https" or not parsed.hostname or parsed.username \
                or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError()
        req = Request(url.rstrip("/") + "/auth/v1/admin/users/" + subject,
            method="DELETE", headers={"apikey": key, "Authorization": "Bearer " + key})
        with build_opener(_NoRedirect()).open(req, timeout=15) as response:
            response.read(131073)
    except HTTPError as exc:
        exc.close()
        if exc.code != 404:
            raise Unavailable() from None
    except Exception:
        raise Unavailable() from None


def find_identity(url, key, email):
    """Resolve legacy accounts without trusting a client-supplied provider ID."""
    parsed = urlsplit(url)
    if not key or parsed.scheme != "https" or not parsed.hostname or parsed.username \
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise Unavailable()
    email = normalize_email(email)
    try:
        deadline = time.monotonic() + 20
        for page in range(1, 101):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Unavailable()
            req = Request(url.rstrip("/") + f"/auth/v1/admin/users?page={page}&per_page=100",
                headers={"apikey": key, "Authorization": "Bearer " + key})
            with build_opener(_NoRedirect()).open(req, timeout=min(5, remaining)) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise Unavailable()
            users = json.loads(raw).get("users")
            if not isinstance(users, list):
                raise Unavailable()
            for user in users:
                if isinstance(user, dict) and str(user.get("email", "")).lower() == email:
                    return str(uuid.UUID(user["id"]))
            if len(users) < 100:
                return None
    except Exception:
        raise Unavailable() from None
    raise Unavailable()
