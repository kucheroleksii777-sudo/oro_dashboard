import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .network import NETUID, RAO_PER_TAO, USER_AGENT, get_network_stats

SPANS = ("1D", "1W", "1M", "1Y", "ALL")
DEFAULT_SPAN = "1D"
MAX_POINTS = 480
CACHE_SECONDS = {
    "1D": 30,
    "1W": 90,
    "1M": 180,
    "1Y": 300,
    "ALL": 300,
}
SOURCE_URL = "https://api.taomarketcap.com/internal/v1/subnets/burn/{netuid}/"
TIMEOUT_SECONDS = 70

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}


def _rao_to_tao(rao: int | float) -> float:
    return float(rao) / RAO_PER_TAO


def _fetch_burn(span: str) -> list[dict]:
    url = f"{SOURCE_URL.format(netuid=NETUID)}?span={span}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    if not isinstance(payload, list):
        return []
    return payload


def _parse_timestamp(value: str) -> int | None:
    try:
        text = value.replace("Z", "+00:00")
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def normalize_points(raw: list[dict]) -> list[dict]:
    points: list[dict] = []
    for item in raw:
        try:
            burn = item.get("burn")
            ts = _parse_timestamp(item.get("timestamp"))
            if burn is None or ts is None:
                continue
            points.append({"t": ts, "tao": _rao_to_tao(int(burn))})
        except (TypeError, ValueError):
            continue
    points.sort(key=lambda point: point["t"])
    return points


def downsample(points: list[dict], max_points: int = MAX_POINTS) -> list[dict]:
    count = len(points)
    if count <= max_points:
        return points

    buckets = max(1, (max_points - 2) // 2)
    inner = points[1:-1]
    out = [points[0]]
    if not inner:
        out.append(points[-1])
        return out

    size = len(inner) / buckets
    start = 0.0
    for index in range(buckets):
        end = int(round((index + 1) * size))
        chunk = inner[int(start) : max(end, int(start) + 1)]
        start = (index + 1) * size
        if not chunk:
            continue
        low = min(chunk, key=lambda point: point["tao"])
        high = max(chunk, key=lambda point: point["tao"])
        if low["t"] == high["t"]:
            out.append(low)
        elif low["t"] < high["t"]:
            out.extend((low, high))
        else:
            out.extend((high, low))
    out.append(points[-1])
    return out


def _empty_payload(span: str) -> dict:
    return {
        "netuid": NETUID,
        "span": span,
        "current_tao": None,
        "points": [],
        "source": SOURCE_URL.format(netuid=NETUID),
        "updated_at": None,
    }


def _with_live_burn(payload: dict) -> dict:
    stats = get_network_stats()
    current = stats.get("reg_tao")
    points = list(payload.get("points") or [])
    if current is not None and points:
        points[-1] = {"t": int(time.time() * 1000), "tao": float(current)}
    return {
        **payload,
        "points": points,
        "current_tao": current if current is not None else payload.get("current_tao"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_registration_history(span: str = DEFAULT_SPAN) -> dict:
    key = span if span in SPANS else DEFAULT_SPAN
    now = time.monotonic()
    cached_payload = None
    with _lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < CACHE_SECONDS[key]:
            cached_payload = cached[1]
    if cached_payload is not None:
        return _with_live_burn(cached_payload)

    payload = _empty_payload(key)
    try:
        raw = _fetch_burn(key)
        points = downsample(normalize_points(raw))
        payload["points"] = points
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        payload = _with_live_burn(payload)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        with _lock:
            cached = _cache.get(key)
            if cached:
                return _with_live_burn(cached[1])
        return payload

    with _lock:
        _cache[key] = (time.monotonic(), payload)
    return payload
