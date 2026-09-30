import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4

from .my_agents import (
    COOLDOWN,
    _miner_auth_headers,
    _slug_submit_error,
    _wallet_class,
    _wallet_job_for_hotkey,
    refresh_my_agents,
    set_hotkey_cooldown,
)
from .network import USER_AGENT

SUBMIT_URL = "https://api.oroagents.com/v1/miner/submit"
MAX_FILE_BYTES = 1_000_000


def _encode_multipart(agent_name: str, filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"----OroAutoSub{uuid4().hex}"
    crlf = b"\r\n"
    safe = filename.replace('"', "").replace("\r", "").replace("\n", "") or "agent.py"
    chunks = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="agent_name"\r\n\r\n',
        agent_name.encode("utf-8"),
        crlf,
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{safe}"\r\n'.encode(),
        b"Content-Type: text/x-python\r\n\r\n",
        content,
        crlf,
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _as_dict(raw: bytes) -> dict:
    try:
        payload = json.loads(raw.decode("utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _reason_from_payload(payload: dict, status_code: int) -> str:
    for key in (
        "error_code",
        "admission_reason",
        "submit_error",
        "reason",
        "code",
        "detail",
        "message",
    ):
        slug = _slug_submit_error(payload.get(key))
        if slug in {"not-registered-onchain", "not-registered", "deregistered", "dereged"}:
            return "dereged"
        if slug:
            return slug
    if status_code == 413:
        return "too-large"
    if status_code == 422:
        return "anti-cheating"
    if status_code == 429:
        return "cooldown"
    if status_code == 400:
        return "invalid-file"
    if status_code:
        return f"http-{status_code}"
    return "submit-failed"


def submit_agent_file(hotkey: str, agent_name: str, filename: str, content: bytes) -> dict:
    name = (agent_name or "").strip()
    now = datetime.now(timezone.utc).isoformat()
    if not hotkey:
        return {
            "ok": False,
            "status": "FAIL",
            "submitted_at": now,
            "next_allowed_at": None,
            "reason": "wallet-not-found",
        }
    if not name:
        return {
            "ok": False,
            "status": "FAIL",
            "submitted_at": now,
            "next_allowed_at": None,
            "reason": "invalid-name",
        }
    if not filename.lower().endswith(".py"):
        return {
            "ok": False,
            "status": "FAIL",
            "submitted_at": now,
            "next_allowed_at": None,
            "reason": "invalid-file",
        }
    if len(content) > MAX_FILE_BYTES:
        return {
            "ok": False,
            "status": "FAIL",
            "submitted_at": now,
            "next_allowed_at": None,
            "reason": "too-large",
        }
    job = _wallet_job_for_hotkey(hotkey)
    if not job:
        return {
            "ok": False,
            "status": "FAIL",
            "submitted_at": now,
            "next_allowed_at": None,
            "reason": "wallet-not-found",
        }
    wallet_name, hotkey_name = job
    try:
        wallet = _wallet_class()(name=wallet_name, hotkey=hotkey_name)
        headers, signed_hot = _miner_auth_headers(wallet)
        if signed_hot != hotkey:
            return {
                "ok": False,
                "status": "FAIL",
                "submitted_at": now,
                "next_allowed_at": None,
                "reason": "hotkey-mismatch",
            }
        body, content_type = _encode_multipart(name, filename, content)
        headers["Content-Type"] = content_type
        headers["User-Agent"] = USER_AGENT
        request = urllib.request.Request(SUBMIT_URL, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            code = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        code = exc.code
        payload = _as_dict(raw)
        next_allowed = payload.get("next_allowed_at")
        if next_allowed:
            set_hotkey_cooldown(hotkey, next_allowed)
            refresh_my_agents()
        return {
            "ok": False,
            "status": "FAIL",
            "submitted_at": now,
            "next_allowed_at": next_allowed,
            "reason": _reason_from_payload(payload, code),
        }
    except Exception:
        return {
            "ok": False,
            "status": "FAIL",
            "submitted_at": now,
            "next_allowed_at": None,
            "reason": "submit-failed",
        }

    payload = _as_dict(raw)
    admission = str(payload.get("admission_status") or "").upper()
    next_allowed = payload.get("next_allowed_at")
    if code == 200 and admission in {"", "ACCEPTED"}:
        if not next_allowed:
            next_allowed = (datetime.now(timezone.utc) + COOLDOWN).isoformat()
        set_hotkey_cooldown(hotkey, next_allowed)
        refresh_my_agents()
        return {
            "ok": True,
            "status": "Success",
            "submitted_at": now,
            "next_allowed_at": next_allowed,
            "reason": None,
        }
    if next_allowed:
        set_hotkey_cooldown(hotkey, next_allowed)
        refresh_my_agents()
    return {
        "ok": False,
        "status": "FAIL",
        "submitted_at": now,
        "next_allowed_at": next_allowed,
        "reason": _reason_from_payload(payload, code) or "rejected",
    }
