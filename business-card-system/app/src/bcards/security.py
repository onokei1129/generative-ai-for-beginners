"""認証・アクセス制御のプリミティブ。

外部依存を増やさないため、パスワードハッシュ（PBKDF2）とTOTPは標準ライブラリで実装する。
本番で Entra ID 等の認証基盤に委譲する場合は、この層を差し替える
（open-issues-v0.3.md 論点B・F 参照）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import struct
import time
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import settings

_PBKDF2_ROUNDS = 240_000


# --------------------------------------------------------------------------
# パスワード
# --------------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
    return hmac.compare_digest(dk.hex(), hash_hex)


# --------------------------------------------------------------------------
# TOTP（多要素認証・要件§6）
# --------------------------------------------------------------------------


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def totp_now(secret: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int((at if at is not None else time.time()) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    """前後 window ステップまで許容する（時刻ずれ対策）。"""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit():
        return False
    now = time.time()
    for drift in range(-window, window + 1):
        if hmac.compare_digest(totp_now(secret, now + drift * 30), code):
            return True
    return False


def totp_provisioning_uri(secret: str, login_id: str, issuer: str = "名刺一元管理システム") -> str:
    from urllib.parse import quote

    return (
        f"otpauth://totp/{quote(issuer)}:{quote(login_id)}"
        f"?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"
    )


# --------------------------------------------------------------------------
# セッション（署名付きCookie）
# --------------------------------------------------------------------------

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="bcards-session")


def dump_session(data: dict[str, Any]) -> str:
    return _serializer.dumps(json.dumps(data, ensure_ascii=False))


def load_session(token: str, max_age_seconds: int) -> dict[str, Any] | None:
    try:
        raw = _serializer.loads(token, max_age=max_age_seconds)
    except BadSignature:
        return None
    except Exception:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


# --------------------------------------------------------------------------
# IPアドレス制限（要件§6）
# --------------------------------------------------------------------------


def ip_in_cidrs(ip: str, cidrs: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr.strip(), strict=False):
                return True
        except ValueError:
            continue
    return False


def is_private_or_loopback(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback
