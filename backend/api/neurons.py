import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .network import NETUID, RAO_PER_TAO, USER_AGENT

BLOCK_SECONDS = 12
CACHE_SECONDS = 45
SOURCE_URL = f"https://api.taomarketcap.com/internal/v1/subnets/neurons/{NETUID}/"
TIMEOUT_SECONDS = 25

_lock = threading.Lock()
_cache: tuple[float, dict] | None = None


def _rao_to_tao(value: object) -> float:
    try:
        return float(value) / RAO_PER_TAO
    except (TypeError, ValueError):
        return 0.0


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _in_immunity(item: dict, now: datetime) -> bool:
    registered = _parse_time(item.get("registration_block_time"))
    if registered is None:
        return False
    try:
        period = int(item.get("immunity_period") or 0)
    except (TypeError, ValueError):
        period = 0
    end = registered.timestamp() + period * BLOCK_SECONDS
    return end > now.timestamp()


def _fetch_neurons() -> list:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    return payload if isinstance(payload, list) else []


def _row(item: dict, in_immunity: bool) -> dict | None:
    uid = item.get("uid")
    if uid is None:
        return None
    try:
        block_at = int(item.get("block_at_registration") or 0)
    except (TypeError, ValueError):
        block_at = 0
    return {
        "uid": int(uid),
        "hotkey": item.get("hotkey") or "",
        "coldkey": item.get("owner") or "",
        "emission": _rao_to_tao(item.get("emission")),
        "registered_at": item.get("registration_block_time"),
        "in_immunity": in_immunity,
        "_block": block_at,
    }


def _public_row(row: dict) -> dict:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _empty_payload() -> dict:
    return {
        "netuid": NETUID,
        "rows": [],
        "to_be_removed": [],
        "source": SOURCE_URL,
        "updated_at": None,
    }


def peek_registered_uids() -> dict:
    with _lock:
        if _cache:
            return _cache[1]
    return _empty_payload()


def get_registered_uids(*, refresh: bool = False) -> dict:
    global _cache
    now_mono = time.monotonic()
    with _lock:
        if not refresh and _cache and now_mono - _cache[0] < CACHE_SECONDS:
            return _cache[1]

    payload = _empty_payload()
    try:
        now = datetime.now(timezone.utc)
        registered: list[dict] = []
        removable: list[dict] = []
        immune: list[dict] = []
        for item in _fetch_neurons():
            if not isinstance(item, dict):
                continue
            immune_now = _in_immunity(item, now)
            row = _row(item, immune_now)
            if row is None:
                continue
            registered.append(row)
            if immune_now:
                immune.append(row)
            else:
                removable.append(row)

        registered.sort(key=lambda row: row.get("registered_at") or "", reverse=True)
        sort_key = lambda row: (row["emission"], row["_block"], row["uid"])
        removable.sort(key=sort_key)
        immune.sort(key=sort_key)
        payload["rows"] = [_public_row(row) for row in registered]
        payload["to_be_removed"] = [_public_row(row) for row in (*removable, *immune)]
        payload["updated_at"] = now.isoformat()
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        with _lock:
            if _cache:
                return _cache[1]
        return payload

    with _lock:
        _cache = (time.monotonic(), payload)
    try:
        from . import store

        store.save_hotkey_owners(
            {
                str(row.get("hotkey") or ""): str(row.get("coldkey") or "")
                for row in payload.get("rows") or []
                if isinstance(row, dict) and row.get("hotkey") and row.get("coldkey")
            }
        )
    except Exception:
        pass
    return payload
