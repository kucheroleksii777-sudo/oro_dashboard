import sys
import threading
import time
from pathlib import Path

from . import store

FINNEY_URL = "wss://entrypoint-finney.opentensor.ai:443"
_NEG_TTL = 3600.0

_lock = threading.Lock()
_negative: dict[str, float] = {}
_substrate_ready = False


def _ensure_substrate() -> bool:
    global _substrate_ready
    if _substrate_ready:
        return True
    try:
        import async_substrate_interface  # noqa: F401
    except ImportError:
        root = Path(__file__).resolve().parents[3]
        for path in sorted((root / "oro").glob(".venv/lib/python*/site-packages")):
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)
        try:
            import async_substrate_interface  # noqa: F401
        except ImportError:
            return False
    _substrate_ready = True
    return True


def _query_chain_owners(hotkeys: list[str]) -> dict[str, str]:
    if not hotkeys or not _ensure_substrate():
        return {}
    from async_substrate_interface import SubstrateInterface

    found: dict[str, str] = {}
    sub = SubstrateInterface(url=FINNEY_URL)
    try:
        for hot in hotkeys:
            try:
                result = sub.query("SubtensorModule", "Owner", [hot])
            except Exception:
                continue
            cold = str(getattr(result, "value", result) or "").strip()
            if cold:
                found[hot] = cold
    finally:
        close = getattr(sub, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
    return found


def resolve_missing_owners(hotkeys: list[str]) -> dict[str, str]:
    wanted = [str(hot or "").strip() for hot in hotkeys]
    wanted = [hot for hot in wanted if hot]
    if not wanted:
        return {}
    now = time.monotonic()
    with _lock:
        try:
            known = store.load_hotkey_owners()
        except Exception:
            known = {}
        pending = [
            hot
            for hot in wanted
            if hot not in known and now - _negative.get(hot, -_NEG_TTL) >= _NEG_TTL
        ]
        if not pending:
            return {hot: known[hot] for hot in wanted if hot in known}
        try:
            found = _query_chain_owners(pending)
        except Exception:
            found = {}
        missed = [hot for hot in pending if hot not in found]
        stamp = time.monotonic()
        for hot in missed:
            _negative[hot] = stamp
        for hot in found:
            _negative.pop(hot, None)
        found.update({hot: known[hot] for hot in wanted if hot in known})
    if found:
        try:
            store.save_hotkey_owners(found)
        except Exception:
            pass
    return found
