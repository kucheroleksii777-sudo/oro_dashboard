import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

NETUID = 15
RAO_PER_TAO = 1_000_000_000
BLOCK_SECONDS = 12.0
CACHE_SECONDS = 8
SOURCE_URL = f"https://api.taomarketcap.com/internal/v1/subnets/{NETUID}/"
TMC_MARKET_URL = "https://api.taomarketcap.com/internal/v1/market/market-data/"
TAOSTATS_URL = "https://taostats.io/subnets/15"
TAO_USD_SOURCES = (
    (
        "https://api.coinbase.com/v2/prices/TAO-USD/spot",
        lambda payload: (payload.get("data") or {}).get("amount"),
    ),
    (
        "https://api.kraken.com/0/public/Ticker?pair=TAOUSD",
        lambda payload: ((payload.get("result") or {}).get("TAOUSD") or {}).get("c", [None])[0],
    ),
    (
        "https://api.binance.com/api/v3/ticker/price?symbol=TAOUSDT",
        lambda payload: payload.get("price"),
    ),
)
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_lock = threading.Lock()
_snap: dict | None = None
_snap_at = 0.0
_last_tao_usd: float | None = None


def _rao_to_tao(rao: int | float) -> float:
    return float(rao) / RAO_PER_TAO


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    return payload if isinstance(payload, dict) else {}


def _tao_usd_from_payload(payload: dict) -> float | None:
    price = _as_float(payload.get("tao_price_usd"))
    if price is None:
        price = _as_float(payload.get("current_price"))
    quote = payload.get("usd_quote")
    if price is None and isinstance(quote, dict):
        price = _as_float(quote.get("price"))
    if price is not None and price > 0:
        return price
    return None


def _tao_usd_from_tmc() -> float:
    price = _tao_usd_from_payload(_fetch_json(TMC_MARKET_URL))
    if price is None:
        raise ValueError("missing TMC tao usd")
    return price


def fetch_tao_usd(*, refresh: bool = False) -> float | None:
    global _last_tao_usd
    try:
        price = _tao_usd_from_tmc()
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, TypeError):
        price = None
        stamp = f"t={int(time.time() * 1000)}"
        for url, extract in TAO_USD_SOURCES:
            request_url = f"{url}{'&' if '?' in url else '?'}{stamp}" if refresh else url
            try:
                price = _as_float(extract(_fetch_json(request_url)))
            except (urllib.error.URLError, TimeoutError, ValueError, OSError, TypeError):
                continue
            if price is not None and price > 0:
                break
            price = None
    if price is not None and price > 0:
        _last_tao_usd = price
        return price
    return None if refresh else _last_tao_usd


def parse_sn15_stats(html: str) -> tuple[float | None, float | None]:
    text = html.replace('\\"', '"').replace("\\u0026", "&")
    reg_tao = None
    alpha_tao = None

    for match in re.finditer(r'"netuid":15\b', text):
        window = text[match.start() : match.start() + 2800]
        if reg_tao is None:
            cost = re.search(r'"neuron_registration_cost":"(\d+)"', window)
            if cost:
                reg_tao = _rao_to_tao(int(cost.group(1)))
        if alpha_tao is None and ('"name":"ORO"' in window or '"symbol":"' in window):
            price = re.search(r'"price":"([0-9.]+)"', window)
            if price:
                alpha_tao = float(price.group(1))
        if reg_tao is not None and alpha_tao is not None:
            break

    return reg_tao, alpha_tao


def _fetch_html() -> str:
    request = urllib.request.Request(
        TAOSTATS_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return response.read().decode("utf-8", errors="ignore")


def _decay_burn_rao(
    burn_rao: int,
    min_burn: int,
    half_life: float,
    fetched_at: float,
    now: float | None = None,
) -> int:
    if burn_rao <= 0 or half_life <= 0:
        return burn_rao
    elapsed_blocks = int(max(0.0, (now or time.time()) - fetched_at) / BLOCK_SECONDS)
    if elapsed_blocks <= 0:
        return burn_rao
    decayed = burn_rao * (0.5 ** (elapsed_blocks / half_life))
    return max(min_burn, int(decayed))


def _snapshot_from_tmc() -> dict:
    subnet_payload: dict = {}
    tao_usd = None

    def _load_subnet() -> dict:
        return _fetch_json(SOURCE_URL)

    def _load_tao() -> float | None:
        return _tao_usd_from_tmc()

    subnet_payload = _load_subnet()
    try:
        tao_usd = _load_tao()
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, TypeError):
        tao_usd = None

    snap = subnet_payload.get("latest_snapshot")
    if not isinstance(snap, dict):
        raise ValueError("missing TMC snapshot")
    burn_rao = _as_int(snap.get("burn"))
    if burn_rao <= 0:
        raise ValueError("missing TMC burn")
    tao_in = _as_int(snap.get("subnet_tao"))
    alpha_in = _as_int(snap.get("subnet_alpha_in"))
    pool_price = (tao_in / alpha_in) if tao_in > 0 and alpha_in > 0 else None
    alpha = pool_price or _as_float(snap.get("price"))
    half_life = _as_float(snap.get("burn_half_life")) or 360.0
    min_burn = _as_int(snap.get("min_burn"), 100_000_000)
    return {
        "burn_rao": burn_rao,
        "min_burn": min_burn,
        "half_life": half_life,
        "alpha_tao": alpha,
        "tao_usd": tao_usd,
        "fetched_at": time.time(),
        "source": SOURCE_URL,
    }


def _snapshot_from_taostats() -> dict:
    html = _fetch_html()
    reg_tao, alpha_tao = parse_sn15_stats(html)
    if reg_tao is None:
        raise ValueError("missing TaoStats burn")
    return {
        "burn_rao": int(round(reg_tao * RAO_PER_TAO)),
        "min_burn": 100_000_000,
        "half_life": 360.0,
        "alpha_tao": alpha_tao,
        "fetched_at": time.time(),
        "source": TAOSTATS_URL,
    }


def _refresh_snapshot(*, force: bool = False) -> dict | None:
    global _snap, _snap_at
    now = time.monotonic()
    with _lock:
        if not force and _snap is not None and now - _snap_at < CACHE_SECONDS:
            return _snap

    snapshot = None
    try:
        snapshot = _snapshot_from_tmc()
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, TypeError, RuntimeError):
        try:
            snapshot = _snapshot_from_taostats()
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, TypeError, RuntimeError):
            snapshot = None

    with _lock:
        if snapshot is not None:
            if _snap is not None and snapshot.get("burn_rao") == _snap.get("burn_rao"):
                snapshot["fetched_at"] = _snap["fetched_at"]
            _snap = snapshot
            _snap_at = time.monotonic()
            return _snap
        return _snap


def get_network_stats(*, refresh: bool = False) -> dict:
    global _last_tao_usd
    try:
        snapshot = _refresh_snapshot(force=refresh)
        tao_usd = snapshot.get("tao_usd") if snapshot else None
        if tao_usd is None:
            tao_usd = fetch_tao_usd(refresh=refresh)
        elif tao_usd > 0:
            _last_tao_usd = tao_usd
        if snapshot is None:
            return {
                "netuid": NETUID,
                "reg_tao": None,
                "alpha_tao": None,
                "tao_usd": tao_usd,
                "source": SOURCE_URL,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

        burn_rao = _decay_burn_rao(
            snapshot["burn_rao"],
            snapshot["min_burn"],
            snapshot["half_life"],
            snapshot["fetched_at"],
        )
        return {
            "netuid": NETUID,
            "reg_tao": _rao_to_tao(burn_rao),
            "alpha_tao": snapshot.get("alpha_tao"),
            "tao_usd": tao_usd,
            "source": snapshot.get("source") or SOURCE_URL,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return {
            "netuid": NETUID,
            "reg_tao": None,
            "alpha_tao": None,
            "tao_usd": _last_tao_usd,
            "source": SOURCE_URL,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
