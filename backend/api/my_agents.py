import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from . import store
from .neurons import get_registered_uids, peek_registered_uids
from .network import USER_AGENT
from .oro import ORO_BASE, _fetch_json

CACHE_SECONDS = 10
COOLDOWN = timedelta(hours=18)
MINER_AGENTS_URL = "https://api.oroagents.com/v1/miner/agents"
RACE_SELECTION_URL = "https://api.oroagents.com/v1/miner/race-selection"
_WALLET_SITE = (
    Path(__file__).resolve().parents[3] / "oro" / ".venv" / "lib" / "python3.12" / "site-packages"
)
_lock = threading.Lock()
_cache: tuple[float, tuple[str, ...], dict] | None = None
_refreshing = False
_refresh_done = threading.Event()
_refresh_done.set()


def clear_my_agents_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def set_hotkey_cooldown(hotkey: str, ends_at: object) -> None:
    key = (hotkey or "").strip()
    parsed = _parse_dt(ends_at) if isinstance(ends_at, str) else None
    if not key or parsed is None:
        return
    iso = parsed.isoformat()
    store.save_hotkey_cooldown(key, iso)
    rows = store.load_my_agent_snapshot()
    changed = False
    for row in rows:
        if isinstance(row, dict) and str(row.get("miner_hotkey") or "") == key:
            row["cooldown_ends_at"] = iso
            changed = True
    if changed:
        store.save_my_agent_snapshot(rows)
    with _lock:
        global _cache
        if not _cache:
            return
        ts, mine_key, payload = _cache
        patched = []
        for row in payload.get("rows") or []:
            if isinstance(row, dict) and str(row.get("miner_hotkey") or "") == key:
                patched.append({**row, "cooldown_ends_at": iso})
            else:
                patched.append(row)
        _cache = (ts, mine_key, {**payload, "rows": patched})


def refresh_my_agents() -> None:
    mine, mine_key = _mine_keys()
    _kick_refresh(mine, mine_key)


def _empty() -> dict:
    return {"rows": [], "updated_at": None, "stale": False, "complete": False}


def _payload_has_agents(payload: dict) -> bool:
    return any(
        isinstance(row, dict) and (row.get("agent_name") or row.get("agent_version_id"))
        for row in (payload.get("rows") or [])
    )


def _snapshot_as_agents() -> list[dict]:
    rows: list[dict] = []
    try:
        stored = store.load_my_agent_snapshot()
    except Exception:
        return rows
    for row in stored:
        if not isinstance(row, dict):
            continue
        if row.get("agent_version_id") or row.get("agent_name"):
            rows.append(row)
    return rows


def _fetch_public(url: str, timeout: float = 10) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))
            return payload if isinstance(payload, dict) else {}
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429 and attempt < 2:
                time.sleep(1.2 * (attempt + 1))
                continue
            return {}
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            return {}
    return {}


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _fetch_hotkey_agents(hotkey: str) -> list[dict]:
    quoted = urllib.parse.quote(hotkey)
    try:
        payload = _fetch_public(f"{ORO_BASE}/leaderboard?q={quoted}&limit=100", timeout=10)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        return []
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    needle = hotkey.lower()
    return [
        item
        for item in entries
        if isinstance(item, dict) and str(item.get("miner_hotkey") or "").lower() == needle
    ]


def _item_state(item: dict) -> str:
    for key in ("state", "evaluation_status"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    value = item.get("status")
    if isinstance(value, str) and value.strip() and " " not in value and "#" not in value:
        return value.strip().upper()
    return ""


def _race_number(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _window_race(item: dict) -> int | None:
    window = item.get("window")
    if not isinstance(window, list):
        return None
    for entry in reversed(window):
        if isinstance(entry, dict):
            number = _race_number(entry.get("race_number"))
            if number:
                return number
    return None


def _window_elim_race(item: dict) -> int | None:
    window = item.get("window")
    if not isinstance(window, list):
        return None
    for seed in (False, True):
        for entry in window:
            if not isinstance(entry, dict):
                continue
            if bool(entry.get("is_seed")) != seed:
                continue
            number = _race_number(entry.get("race_number"))
            if number:
                return number
    return None


def _eliminated_race_from_text(value: object) -> int | None:
    if not isinstance(value, str) or "Eliminated" not in value:
        return None
    match = re.search(r"(?i)race\s*#\s*(\d+)", value)
    return int(match.group(1)) if match else None


def _eliminated_status(race: int | None) -> str:
    if race:
        return f"Eliminated\nRace #{race}"
    return "Eliminated"


def _status_race_number(item: dict) -> int | None:
    text = str(item.get("status") or "")
    match = re.search(r"(?i)race\s*#\s*(\d+)", text)
    return int(match.group(1)) if match else None


def _old_season_race(number: int | None) -> bool:
    return number is not None and number >= 100


NEW_AGENT_PIN_AFTER = datetime(2026, 9, 10, tzinfo=timezone.utc)


def _status_is_current(status: object) -> bool:
    text = str(status or "").replace("_", " ").replace("-", " ").lower()
    first = text.split("\n", 1)[0].strip()
    if first in {"running", "received"}:
        return True
    return "qualifying" in first and "drop" not in first


def _submitted_from_now(submitted_at: object) -> bool:
    parsed = _parse_dt(submitted_at)
    return parsed is not None and parsed >= NEW_AGENT_PIN_AFTER


def _status_is_new(status: object, submitted_at: object = None) -> bool:
    text = str(status or "").replace("_", " ").replace("-", " ").lower()
    first = text.split("\n", 1)[0].strip()
    if not first or "drop" in first or "eliminat" in first:
        return False
    if _status_is_current(first):
        return False
    if first != "queued" and not first.startswith("queued"):
        return False
    return _submitted_from_now(submitted_at)


def _new_mechanism_membership() -> tuple[set[str], dict[str, int]]:
    new_ids: set[str] = set()
    last_old: dict[str, int] = {}
    try:
        summaries = store.load_all_race_summaries()
    except Exception:
        summaries = {}
    for summary in summaries.values():
        if not isinstance(summary, dict):
            continue
        race_id = str(summary.get("race_id") or "")
        number = _race_number(summary.get("race_number"))
        tf = store.is_tf_race(summary) or (number is not None and number < 100)
        try:
            table = store.load_race_table(race_id) if race_id else None
        except Exception:
            table = None
        for row in (table or {}).get("rows") or []:
            if not isinstance(row, dict):
                continue
            version_id = str(row.get("agent_version_id") or "")
            if not version_id:
                continue
            if tf:
                new_ids.add(version_id)
                continue
            if number and (last_old.get(version_id) is None or number > last_old[version_id]):
                last_old[version_id] = number
    try:
        standings = store.load_current_standings() or {}
    except Exception:
        standings = {}
    current = _race_number(standings.get("race_number"))
    if store.is_tf_race(standings) or (current is not None and current < 100):
        for row in standings.get("rows") or []:
            if not isinstance(row, dict):
                continue
            version_id = str(row.get("agent_version_id") or "")
            if version_id:
                new_ids.add(version_id)
    return new_ids, last_old


def _old_mechanism_elim_race(
    item: dict,
    version_id: str,
    new_ids: set[str],
    last_old: dict[str, int],
) -> int | None:
    if not version_id or version_id in new_ids:
        return None
    if _item_state(item) in {"RUNNING", "RECEIVED"}:
        return None
    race = last_old.get(version_id)
    if race:
        return race
    for number in (
        _window_race(item),
        _status_race_number(item),
        _race_number(item.get("eliminated_in_race_number")),
    ):
        if _old_season_race(number):
            return number
    return None


_SUBMIT_ERROR_ALIASES = {
    "file_too_large": "too-large",
    "too_large": "too-large",
    "payload_too_large": "too-large",
    "anti_cheating": "anti-cheating",
    "anticheating": "anti-cheating",
    "cheating": "anti-cheating",
    "code_analysis_error": "anti-cheating",
    "code_analysis": "anti-cheating",
    "static_analysis": "anti-cheating",
}
_SUBMIT_ERROR_SKIP = {
    "eliminated",
    "discarded",
    "cancelled",
    "below_threshold",
    "below-threshold",
    "not_eligible",
    "not-eligible",
    "eligible",
    "queued",
    "running",
    "received",
    "cooldown",
    "qualifying",
}


def _slug_submit_error(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.split("\n", 1)[0].split(":", 1)[0].strip()
    key = re.sub(r"[\s-]+", "_", text.lower())
    if key in _SUBMIT_ERROR_SKIP:
        return ""
    if key in _SUBMIT_ERROR_ALIASES:
        return _SUBMIT_ERROR_ALIASES[key]
    if re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)+", key):
        return key.replace("_", "-")
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", text.lower()):
        return text.lower()
    return ""


def _submit_error(item: dict) -> str:
    for key in (
        "submit_error",
        "admission_reason",
        "discard_reason",
        "error_code",
        "error",
        "failure_reason",
        "last_error",
        "reject_reason",
        "rejection_reason",
        "reason",
    ):
        slug = _slug_submit_error(item.get(key))
        if slug:
            return slug
    return ""


def _as_score(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _q_beats_threshold(score: object, threshold: object) -> bool | None:
    left = _as_score(score)
    right = _as_score(threshold)
    if left is None or right is None:
        return None
    if left <= 1 and right > 1:
        left *= 100
    elif right <= 1 and left > 1:
        right *= 100
    return left >= right


def _window_score(item: dict) -> float | None:
    window = item.get("window")
    if not isinstance(window, list):
        return None
    for entry in reversed(window):
        if not isinstance(entry, dict):
            continue
        for key in ("raw_score", "qualifying_score", "final_score", "score"):
            value = _as_score(entry.get(key))
            if value is not None:
                return value
    return None


def _agent_q_score(item: dict, standing_q: object = None) -> float | None:
    for value in (
        standing_q,
        item.get("qualifying_score"),
        item.get("final_score"),
        _window_score(item),
    ):
        score = _as_score(value)
        if score is not None:
            return score
    return None


def _below_threshold(item: dict) -> bool:
    for key in ("selection_fallback_reason", "pin_disabled_reason"):
        if str(item.get(key) or "").strip().lower() == "below_threshold":
            return True
    return False


def _race_status_label(label: str, race: int | None) -> str:
    return f"{label}\nRace #{race}" if race else label


def _format_agent_status(
    item: dict,
    current_race: int | None = None,
    qualifying_score: object = None,
    threshold: object = None,
    sibling_pinned: bool = False,
    in_current_race: bool = False,
    pinned: bool = False,
) -> str:
    existing = item.get("status")
    if isinstance(existing, str):
        existing = existing.replace("(", "").replace(")", "")
    error = _submit_error(item)
    if not error and isinstance(existing, str):
        first = existing.split("\n", 1)[0]
        error = _slug_submit_error(first)
    if error:
        race = (
            _race_number(item.get("eliminated_in_race_number"))
            or _window_race(item)
            or current_race
        )
        return f"{error}\nRace #{race}" if race else error
    eliminated = _race_number(item.get("eliminated_in_race_number"))
    if eliminated is None:
        eliminated = _eliminated_race_from_text(existing)
    if eliminated is None and (
        item.get("eliminated_at")
        or (isinstance(existing, str) and "Eliminated" in existing)
    ):
        eliminated = _window_elim_race(item)
    if eliminated or item.get("eliminated_at") or (
        isinstance(existing, str) and "Eliminated" in existing
    ):
        return _eliminated_status(eliminated)
    score = _agent_q_score(item, qualifying_score)
    state = _item_state(item)
    if state in {"RUNNING", "RECEIVED"}:
        return state.title()
    if (in_current_race or pinned) and state not in {"CANCELLED", "DISCARDED"}:
        race = current_race or _window_race(item)
        return _race_status_label("Qualifying In", race)
    if state == "QUEUED":
        return "Queued"
    outranked = bool(item.get("outranked_by_agent_version_id"))
    if score is None:
        return "Queued"
    if _below_threshold(item) or _q_beats_threshold(score, threshold) is False:
        return "Dropped"
    if state in {"CANCELLED", "DISCARDED"}:
        return state.title()
    race = current_race or _window_race(item)
    in_qualifying = (
        state == "ELIGIBLE"
        or item.get("is_active_qualifier")
        or item.get("is_selected_for_race")
        or item.get("final_score") is not None
        or score is not None
        or (
            isinstance(existing, str)
            and ("Qualifying" in existing or "Queued" in existing)
        )
    )
    if in_qualifying:
        return _race_status_label("Qualifying In", race) if pinned else "Queued"
    if state == "ELIGIBLE" or sibling_pinned or outranked or score is not None:
        return _race_status_label("Qualifying In", race) if pinned else "Queued"
    return state.replace("_", " ").title() if state else "Dropped"


def _merge_agent_records(agents: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    leftover: list[dict] = []
    for item in agents:
        if not isinstance(item, dict):
            continue
        version_id = str(item.get("agent_version_id") or "")
        if not version_id:
            leftover.append(item)
            continue
        current = by_id.get(version_id)
        if current is None:
            by_id[version_id] = dict(item)
            continue
        for key, value in item.items():
            if value in (None, "", []):
                continue
            if current.get(key) in (None, "", []):
                current[key] = value
    return list(by_id.values()) + leftover


def _safe_neurons() -> list[dict]:
    peeked = peek_registered_uids().get("rows") or []
    if peeked:
        return [item for item in peeked if isinstance(item, dict) and item.get("hotkey")]
    try:
        rows = get_registered_uids().get("rows") or []
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return []
    return [item for item in rows if isinstance(item, dict) and item.get("hotkey")]


def _safe_standings() -> dict:
    stored = store.load_current_standings()
    if isinstance(stored, dict) and stored.get("rows"):
        return stored
    return {}


def _wallet_class():
    try:
        from bittensor_wallet import Wallet
    except ImportError:
        site = str(_WALLET_SITE)
        if _WALLET_SITE.is_dir() and site not in sys.path:
            sys.path.insert(0, site)
        from bittensor_wallet import Wallet
    return Wallet


def _miner_auth_headers(wallet) -> tuple[dict[str, str], str]:
    hotkey = wallet.hotkey.ss58_address
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    nonce = str(uuid4())
    signed = wallet.hotkey.sign(f"{hotkey}:{timestamp}:{nonce}".encode())
    signature = signed.hex() if isinstance(signed, bytes) else str(signed)
    if not signature.startswith("0x"):
        signature = f"0x{signature}"
    return {
        "User-Agent": "oro-dashboard",
        "Accept": "application/json",
        "X-Hotkey": hotkey,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }, hotkey


def _fetch_miner_payload(wallet_name: str, hotkey_name: str) -> tuple[str, dict]:
    try:
        wallet = _wallet_class()(name=wallet_name, hotkey=hotkey_name)
        headers, hotkey = _miner_auth_headers(wallet)
        request = urllib.request.Request(MINER_AGENTS_URL, headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", errors="ignore"))
    except Exception:
        return "", {}
    return hotkey, payload if isinstance(payload, dict) else {}


def _agents_from_miner_payload(hotkey: str, payload: dict) -> list[dict]:
    rows: list[dict] = []
    racing_id = str(payload.get("racing_agent_version_id") or "")
    for agent in payload.get("agents") or []:
        if not isinstance(agent, dict):
            continue
        latest = agent.get("latest_version")
        if not isinstance(latest, dict):
            latest = agent
        version_id = str(
            latest.get("agent_version_id")
            or agent.get("agent_version_id")
            or agent.get("latest_agent_version_id")
            or ""
        )
        if not version_id:
            continue
        rows.append(
            {
                "agent_version_id": version_id,
                "agent_name": agent.get("agent_name") or latest.get("agent_name") or "",
                "version_number": latest.get("version_number") or agent.get("version_number"),
                "miner_hotkey": str(agent.get("miner_hotkey") or latest.get("miner_hotkey") or hotkey or ""),
                "submitted_at": latest.get("submitted_at") or agent.get("submitted_at"),
                "is_active_qualifier": bool(
                    latest.get("is_active_qualifier")
                    or latest.get("is_selected_for_race")
                    or agent.get("is_selected_for_race")
                ),
                "is_selected_for_race": bool(
                    latest.get("is_selected_for_race")
                    or agent.get("is_selected_for_race")
                    or (racing_id and version_id == racing_id)
                ),
                "racing_agent_version_id": racing_id,
                "state": latest.get("state") or agent.get("state"),
                "eliminated_at": latest.get("eliminated_at") or agent.get("eliminated_at"),
                "eliminated_in_race_number": latest.get("eliminated_in_race_number")
                or agent.get("eliminated_in_race_number"),
                "final_score": latest.get("final_score") or agent.get("final_score"),
                "qualifying_score": latest.get("qualifying_score") or agent.get("qualifying_score"),
                "window": latest.get("window") or agent.get("window"),
                "selection_fallback_reason": latest.get("selection_fallback_reason")
                or agent.get("selection_fallback_reason"),
                "is_pinnable": latest.get("is_pinnable")
                if latest.get("is_pinnable") is not None
                else agent.get("is_pinnable"),
                "pin_disabled_reason": latest.get("pin_disabled_reason")
                or agent.get("pin_disabled_reason"),
                "outranked_by_agent_version_id": latest.get("outranked_by_agent_version_id")
                or agent.get("outranked_by_agent_version_id"),
                "submit_error": latest.get("submit_error") or agent.get("submit_error"),
                "admission_reason": latest.get("admission_reason") or agent.get("admission_reason"),
                "discard_reason": latest.get("discard_reason") or agent.get("discard_reason"),
                "error_code": latest.get("error_code") or agent.get("error_code"),
                "error": latest.get("error") or agent.get("error"),
                "failure_reason": latest.get("failure_reason") or agent.get("failure_reason"),
                "last_error": latest.get("last_error") or agent.get("last_error"),
                "reject_reason": latest.get("reject_reason") or agent.get("reject_reason"),
                "rejection_reason": latest.get("rejection_reason")
                or agent.get("rejection_reason"),
                "reason": latest.get("reason") or agent.get("reason"),
            }
        )
    return rows


def _miner_state() -> tuple[dict[str, datetime], list[dict]]:
    jobs: list[tuple[str, str]] = []
    root = Path.home() / ".bittensor" / "wallets"
    if root.is_dir():
        for pub in root.glob("*/hotkeys/*pub.txt"):
            label = pub.name.removesuffix("pub.txt")
            wallet_name = pub.parent.parent.name
            if label and wallet_name:
                jobs.append((wallet_name, label))
    allowed: dict[str, datetime] = {}
    agents: list[dict] = []
    if not jobs:
        return allowed, agents
    for wallet_name, hotkey_name in jobs:
        ss58, payload = _fetch_miner_payload(wallet_name, hotkey_name)
        if not ss58 or not payload:
            continue
        when = _parse_dt(payload.get("next_allowed_at"))
        if when:
            allowed[ss58] = when
        agents.extend(_agents_from_miner_payload(ss58, payload))
    return allowed, agents


def _next_allowed_by_hotkey() -> dict[str, datetime]:
    allowed, _agents = _miner_state()
    return allowed


def _eval_queue_agents(hotkeys: set[str]) -> list[dict]:
    if not hotkeys:
        return []
    batches: list[tuple[str, list]] = []
    try:
        pending = _fetch_json(f"{ORO_BASE}/evaluations/pending", timeout=8, quick=True)
        batches.append(("pending", [item for item in (pending.get("items") or []) if isinstance(item, dict)]))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        pass
    try:
        running = _fetch_json(f"{ORO_BASE}/evaluations/running", timeout=8, quick=True)
        extra = running if isinstance(running, list) else running.get("items") or []
        batches.append(("running", [item for item in extra if isinstance(item, dict)]))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        pass
    rows = []
    for label, items in batches:
        for item in items:
            hotkey = str(item.get("miner_hotkey") or "")
            version_id = str(item.get("agent_version_id") or "")
            if not version_id or hotkey not in hotkeys:
                continue
            rows.append(
                {
                    "agent_version_id": version_id,
                    "agent_name": item.get("agent_name") or "",
                    "version_number": item.get("version_number"),
                    "miner_hotkey": hotkey,
                    "submitted_at": item.get("queued_at") or item.get("started_at"),
                    "is_active_qualifier": True,
                    "status": "RUNNING" if label == "running" else "QUEUED",
                }
            )
    return rows


def _ss58_from_pub(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("ss58Address") or data.get("ss58_address") or "")


def _wallet_hotkeys() -> dict[str, tuple[str, float]]:
    names: dict[str, tuple[str, float]] = {}
    root = Path.home() / ".bittensor" / "wallets"
    if not root.is_dir():
        return names
    for pub in root.glob("*/hotkeys/*pub.txt"):
        label = pub.name.removesuffix("pub.txt")
        if not label:
            continue
        ss58 = _ss58_from_pub(pub)
        if ss58:
            names[ss58] = (label, pub.stat().st_mtime)
    return names


def _wallet_cold_by_hot() -> dict[str, str]:
    mapping: dict[str, str] = {}
    root = Path.home() / ".bittensor" / "wallets"
    if not root.is_dir():
        return mapping
    for wallet_dir in root.iterdir():
        if not wallet_dir.is_dir():
            continue
        cold_pub = wallet_dir / "coldkeypub.txt"
        cold = _ss58_from_pub(cold_pub) if cold_pub.is_file() else ""
        if not cold:
            continue
        hot_dir = wallet_dir / "hotkeys"
        if not hot_dir.is_dir():
            continue
        for pub in hot_dir.glob("*pub.txt"):
            hot = _ss58_from_pub(pub)
            if hot:
                mapping[hot] = cold
    return mapping


def _wallet_job_for_hotkey(hotkey: str) -> tuple[str, str] | None:
    root = Path.home() / ".bittensor" / "wallets"
    if not hotkey or not root.is_dir():
        return None
    for pub in root.glob("*/hotkeys/*pub.txt"):
        if _ss58_from_pub(pub) == hotkey:
            return pub.parent.parent.name, pub.name.removesuffix("pub.txt")
    return None


def _queued_status_for_pin(row: dict, race: object = None) -> str:
    status = str(row.get("status") or "")
    if row.get("eliminated_in_race_number") or row.get("eliminated_at") or "Eliminated" in status:
        return status
    if _submit_error(row) or _slug_submit_error(status.split("\n", 1)[0]):
        return status
    number = _race_number(race)
    if number is None:
        match = re.search(r"#\s*(\d+)", status)
        number = _race_number(match.group(1) if match else None)
    return _race_status_label("Qualifying In", number)


def _row_is_eliminated(row: dict) -> bool:
    if row.get("eliminated_in_race_number") is not None:
        return True
    status = str(row.get("status") or "")
    return "Eliminated" in status


def _pin_candidate_key(row: dict) -> tuple:
    parsed = _parse_dt(row.get("submitted_at"))
    return (
        row.get("qualifying_score") if row.get("qualifying_score") is not None else -1.0,
        1 if row.get("in_current_race") else 0,
        row.get("version_number") or 0,
        parsed.timestamp() if parsed else 0.0,
    )


def _highest_pin_candidate(
    group: list[dict],
    threshold: object = None,
) -> dict | None:
    candidates = []
    for row in group:
        if _row_is_eliminated(row):
            continue
        if str(row.get("status") or "") == "Dropped":
            continue
        if _q_beats_threshold(row.get("qualifying_score"), threshold) is False:
            continue
        if row.get("qualifying_score") is None and not row.get("in_current_race"):
            continue
        candidates.append(row)
    if not candidates:
        return None
    return max(candidates, key=_pin_candidate_key)


def _enforce_single_pin(
    rows: list[dict],
    threshold: object = None,
    current_ids: set[str] | None = None,
    current_race: object = None,
) -> None:
    current_ids = current_ids or set()
    groups: dict[str, list[dict]] = {}
    for row in rows:
        hotkey = str(row.get("miner_hotkey") or "")
        if hotkey:
            groups.setdefault(hotkey, []).append(row)
    for group in groups.values():
        pinned = [row for row in group if row.get("pinned")]
        live_pinned = [row for row in pinned if not _row_is_eliminated(row)]
        dead_pinned = [row for row in pinned if _row_is_eliminated(row)]
        if dead_pinned and not live_pinned:
            for row in dead_pinned:
                row["pinned"] = False
                row["pinnable"] = False
            chosen = _highest_pin_candidate(group, threshold)
            if chosen is not None:
                chosen["pinned"] = True
                chosen["pinnable"] = False
                if not _row_is_eliminated(chosen):
                    chosen["status"] = _race_status_label(
                        "Qualifying In",
                        _race_number(current_race),
                    )
            continue
        if len(live_pinned) <= 1:
            for row in dead_pinned:
                row["pinned"] = False
                row["pinnable"] = False
            continue
        live_pinned.sort(
            key=lambda row: (
                1 if str(row.get("agent_version_id") or "") in current_ids else 0,
                1 if row.get("is_active_qualifier") else 0,
                row.get("version_number") or 0,
                _parse_dt(row.get("submitted_at")).timestamp()
                if _parse_dt(row.get("submitted_at"))
                else 0.0,
            ),
            reverse=True,
        )
        for row in (*live_pinned[1:], *dead_pinned):
            row["pinned"] = False
            row["is_active_qualifier"] = False
            eliminated = _row_is_eliminated(row)
            row["pinnable"] = bool(
                not eliminated
                and _q_beats_threshold(row.get("qualifying_score"), threshold) is True
            )
            status = str(row.get("status") or "")
            if not eliminated and (
                "Qualifying" in status or "Queued" in status or status == ""
            ):
                row["status"] = "Queued"


def _apply_pin_to_rows(rows: list[dict], version_id: str, hotkey: str) -> list[dict]:
    race = None
    try:
        race = (store.load_current_standings() or {}).get("race_number")
    except Exception:
        race = None
    if race is None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            match = re.search(r"#\s*(\d+)", str(row.get("status") or ""))
            if match:
                race = int(match.group(1))
                break
    updated: list[dict] = []
    for row in rows:
        item = dict(row)
        if str(item.get("miner_hotkey") or "") == hotkey:
            if str(item.get("agent_version_id") or "") == version_id:
                item["pinned"] = True
                item["pinnable"] = False
                item["is_selected_for_race"] = True
                item["is_active_qualifier"] = True
                item["status"] = _queued_status_for_pin(item, race)
            elif item.get("pinned") or item.get("is_selected_for_race") or item.get("is_active_qualifier"):
                item["pinned"] = False
                item["pinnable"] = True
                item["is_selected_for_race"] = False
                item["is_active_qualifier"] = False
                item["status"] = _format_agent_status(
                    item, current_race=_race_number(race), pinned=False
                )
        updated.append(item)
    _enforce_single_pin(updated)
    return updated


def _apply_pin_locally(version_id: str, hotkey: str) -> None:
    global _cache
    with _lock:
        if _cache:
            ts, mine_key, payload = _cache
            rows = _apply_pin_to_rows(list(payload.get("rows") or []), version_id, hotkey)
            _cache = (ts, mine_key, {**payload, "rows": rows})
    snapshot = store.load_my_agent_snapshot()
    if snapshot:
        store.save_my_agent_snapshot(_apply_pin_to_rows(snapshot, version_id, hotkey))


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    raw = exc.read().decode("utf-8", errors="ignore")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw or str(exc.reason)
    if isinstance(parsed, dict):
        return str(parsed.get("detail") or parsed.get("message") or raw or exc.reason)
    if isinstance(parsed, list) and parsed:
        return str(parsed[0])
    return raw or str(exc.reason)


def pin_agent_version(version_id: str, hotkey: str) -> dict:
    job = _wallet_job_for_hotkey(hotkey)
    if not job:
        return {"ok": False, "error": "wallet not found", "status": 404}
    wallet_name, hotkey_name = job
    try:
        wallet = _wallet_class()(name=wallet_name, hotkey=hotkey_name)
        headers, signed_hot = _miner_auth_headers(wallet)
        if signed_hot != hotkey:
            return {"ok": False, "error": "hotkey mismatch", "status": 400}
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            RACE_SELECTION_URL,
            data=json.dumps({"agent_version_id": version_id}).encode("utf-8"),
            headers=headers,
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": _http_error_detail(exc), "status": exc.code}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "status": 502}
    _apply_pin_locally(version_id, hotkey)
    return {"ok": True}


def _missing_elim_race(item: dict) -> bool:
    if _race_number(item.get("eliminated_in_race_number")) or _eliminated_race_from_text(
        item.get("status")
    ):
        return False
    if item.get("eliminated_at"):
        return True
    status = item.get("status")
    return isinstance(status, str) and "Eliminated" in status


def _fill_missing_elim_races(agents: list[dict]) -> None:
    need = [
        str(item.get("agent_version_id") or "")
        for item in agents
        if item.get("agent_version_id") and _missing_elim_race(item)
    ]
    need = list(dict.fromkeys(need))
    if not need:
        return
    fetched = [_fetch_submitted_at(version_id) for version_id in need]
    meta_by_id = {version_id: meta for version_id, _submitted, meta in fetched if meta}
    for item in agents:
        extra = meta_by_id.get(str(item.get("agent_version_id") or "")) or {}
        for key, value in extra.items():
            if value not in (None, "", []) and not item.get(key):
                item[key] = value
        if not _race_number(item.get("eliminated_in_race_number")):
            race = _window_elim_race(item)
            if race:
                item["eliminated_in_race_number"] = race


def _fetch_submitted_at(version_id: str) -> tuple[str, datetime | None, dict]:
    if not version_id:
        return version_id, None, {}
    try:
        data = _fetch_public(f"{ORO_BASE}/agent-versions/{version_id}/status", timeout=10)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        return version_id, None, {}
    return (
        version_id,
        _parse_dt(data.get("submitted_at")),
        {
            "state": data.get("state"),
            "eliminated_at": data.get("eliminated_at"),
            "eliminated_in_race_number": data.get("eliminated_in_race_number"),
            "is_active_qualifier": data.get("is_active_qualifier"),
            "final_score": data.get("final_score"),
            "qualifying_score": data.get("qualifying_score"),
            "window": data.get("window"),
            "is_pinnable": data.get("is_pinnable"),
            "selection_fallback_reason": data.get("selection_fallback_reason"),
            "pin_disabled_reason": data.get("pin_disabled_reason"),
            "submit_error": data.get("submit_error"),
            "admission_reason": data.get("admission_reason"),
            "discard_reason": data.get("discard_reason"),
            "error_code": data.get("error_code"),
            "error": data.get("error"),
            "failure_reason": data.get("failure_reason"),
            "last_error": data.get("last_error"),
            "reject_reason": data.get("reject_reason"),
            "rejection_reason": data.get("rejection_reason"),
            "reason": data.get("reason"),
        },
    )


def _mine_keys() -> tuple[list[dict], tuple[str, ...]]:
    mine = [
        item
        for item in store.list_keys()
        if item.get("group") == store.GROUP_MINE
        or str(item.get("nickname") or "").strip().lower() == "po"
    ]
    return mine, tuple(sorted(item["ss58"] for item in mine))


def _snapshot_payload() -> dict | None:
    rows = store.load_my_agent_snapshot()
    if not rows:
        return None
    return {"rows": rows, "updated_at": None, "stale": True, "complete": True}


def _kick_refresh(mine: list[dict], mine_key: tuple[str, ...]) -> None:
    global _refreshing
    with _lock:
        if _refreshing:
            return
        _refreshing = True
        _refresh_done.clear()

    def _run() -> None:
        global _refreshing, _cache
        try:
            payload = _build_my_agents(mine, mine_key)
            with _lock:
                _cache = (time.monotonic(), mine_key, payload)
        except Exception:
            pass
        finally:
            with _lock:
                _refreshing = False
            _refresh_done.set()

    threading.Thread(target=_run, daemon=True, name="my-agents-refresh").start()


def get_my_agents(*, wait: bool = False) -> dict:
    global _cache, _refreshing
    mine, mine_key = _mine_keys()
    now_mono = time.monotonic()
    with _lock:
        if (
            _cache
            and now_mono - _cache[0] < CACHE_SECONDS
            and _cache[1] == mine_key
            and _payload_has_agents(_cache[2])
        ):
            return {**_cache[2], "stale": False}
        if _refreshing:
            waiter = True
        else:
            waiter = False
            _refreshing = True
            _refresh_done.clear()
    if waiter:
        _refresh_done.wait(timeout=90)
        with _lock:
            if _cache and _cache[1] == mine_key:
                return {**_cache[2], "stale": False}
        return _empty()
    try:
        payload = _build_my_agents(mine, mine_key)
        if _payload_has_agents(payload):
            with _lock:
                _cache = (time.monotonic(), mine_key, payload)
        return {**payload, "stale": False}
    except Exception:
        with _lock:
            if _cache and _cache[1] == mine_key:
                return {**_cache[2], "stale": False}
        return _empty()
    finally:
        with _lock:
            _refreshing = False
        _refresh_done.set()


def _build_my_agents(mine: list[dict], mine_key: tuple[str, ...]) -> dict:
    global _cache
    payload = _empty()
    saved_colds = {item["ss58"] for item in mine if item.get("kind") == store.KIND_COLD}
    saved_hots = {item["ss58"] for item in mine if item.get("kind") == store.KIND_HOT}
    remembered = store.load_my_hotkeys()
    wallet = _wallet_hotkeys()
    wallet_colds = _wallet_cold_by_hot()
    if not saved_colds and not saved_hots and not wallet:
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        with _lock:
            _cache = (time.monotonic(), mine_key, payload)
        return payload

    try:
        by_hot = {
            str(item.get("hotkey") or ""): item
            for item in _safe_neurons()
        }
        colds = set(saved_colds)
        for hotkey in saved_hots:
            owner = str(
                (by_hot.get(hotkey) or {}).get("coldkey")
                or (remembered.get(hotkey) or {}).get("coldkey")
                or wallet_colds.get(hotkey)
                or ""
            )
            if owner:
                colds.add(owner)
        for hotkey, owner in wallet_colds.items():
            if hotkey in wallet and owner:
                colds.add(owner)
        hotkeys = set(saved_hots)
        hotkeys.update(wallet)
        hotkeys.update(remembered)
        for item in by_hot.values():
            if str(item.get("coldkey") or "") in colds:
                hotkeys.add(str(item.get("hotkey") or ""))
        for item in remembered.values():
            if str(item.get("coldkey") or "") in colds:
                hotkeys.add(str(item.get("ss58") or ""))
        hotkeys.discard("")
        agents: list[dict] = []
        try:
            next_allowed, miner_agents = _miner_state()
        except Exception:
            next_allowed, miner_agents = {}, []
        stored_next_allowed: dict[str, datetime] = {}
        for hotkey, raw in store.load_hotkey_cooldowns().items():
            when = _parse_dt(raw)
            if when:
                stored_next_allowed[hotkey] = when
        if miner_agents:
            agents.extend(miner_agents)
        leaderboard_hits = 0
        if hotkeys:
            for hotkey in hotkeys:
                batch = _fetch_hotkey_agents(hotkey)
                if batch:
                    leaderboard_hits += 1
                agents.extend(batch)
        agents.extend(_eval_queue_agents(hotkeys))
        snapshot_agents = _snapshot_as_agents()
        if not any(str(item.get("agent_version_id") or "") for item in agents):
            agents.extend(snapshot_agents)
        else:
            have_ids = {str(item.get("agent_version_id") or "") for item in agents}
            have_ids.discard("")
            snap_by_id = {
                str(row.get("agent_version_id") or ""): row
                for row in snapshot_agents
                if row.get("agent_version_id")
            }
            for item in agents:
                version_id = str(item.get("agent_version_id") or "")
                prior = snap_by_id.get(version_id) or {}
                if not item.get("agent_name") and prior.get("agent_name"):
                    item["agent_name"] = prior.get("agent_name")
                if item.get("version_number") is None and prior.get("version_number") is not None:
                    item["version_number"] = prior.get("version_number")
                if not _format_agent_status(item) and prior.get("status"):
                    item["status"] = prior.get("status")
                if isinstance(prior.get("status"), str) and "Eliminated" in prior["status"]:
                    if not item.get("eliminated_at") and not _race_number(
                        item.get("eliminated_in_race_number")
                    ):
                        item["status"] = prior["status"]
                prior_elim = _race_number(prior.get("eliminated_in_race_number")) or (
                    _eliminated_race_from_text(prior.get("status"))
                )
                if not _race_number(item.get("eliminated_in_race_number")) and prior_elim:
                    item["eliminated_in_race_number"] = prior_elim
                if not item.get("eliminated_at") and prior.get("eliminated_at"):
                    item["eliminated_at"] = prior.get("eliminated_at")
                if prior.get("pinned"):
                    item["pinned"] = True
            for row in snapshot_agents:
                version_id = str(row.get("agent_version_id") or "")
                if version_id and version_id not in have_ids:
                    agents.append(row)
                    have_ids.add(version_id)
        agents = _merge_agent_records(agents)
        all_version_ids = [
            str(item.get("agent_version_id") or "")
            for item in agents
            if item.get("agent_version_id")
        ]
        stored_status, _, _, _, _ = store.load_agents(all_version_ids)
        submitted_by_id: dict[str, datetime] = {}
        for version_id, row in stored_status.items():
            parsed = _parse_dt(row.get("submitted_at"))
            if parsed:
                submitted_by_id[version_id] = parsed
        pinned_hots_early = {
            str(item.get("miner_hotkey") or "")
            for item in agents
            if item.get("miner_hotkey")
            and (item.get("is_active_qualifier") or item.get("is_selected_for_race"))
        }
        version_ids = [
            str(item.get("agent_version_id") or "")
            for item in agents
            if item.get("agent_version_id")
            and (
                str(item.get("agent_version_id") or "") not in submitted_by_id
                or (
                    (
                        item.get("eliminated_at")
                        or (
                            isinstance(item.get("status"), str)
                            and "Eliminated" in str(item.get("status"))
                        )
                    )
                    and not _race_number(item.get("eliminated_in_race_number"))
                    and not _eliminated_race_from_text(item.get("status"))
                )
                or (
                    _agent_q_score(item) is None
                    and str(item.get("miner_hotkey") or "") in pinned_hots_early
                    and not item.get("is_active_qualifier")
                )
            )
        ]
        version_ids = list(dict.fromkeys(version_ids))
        if version_ids:
            try:
                with ThreadPoolExecutor(max_workers=min(4, len(version_ids))) as pool:
                    fetched = list(pool.map(_fetch_submitted_at, version_ids))
            except RuntimeError:
                fetched = [_fetch_submitted_at(version_id) for version_id in version_ids]
            meta_by_id = {}
            for version_id, submitted, meta in fetched:
                if submitted:
                    submitted_by_id[version_id] = submitted
                    code = (stored_status.get(version_id) or {}).get("code") or "private"
                    store.save_agent_status(version_id, code, submitted.isoformat())
                if meta:
                    meta_by_id[version_id] = meta
            for item in agents:
                version_id = str(item.get("agent_version_id") or "")
                extra = meta_by_id.get(version_id) or {}
                for key, value in extra.items():
                    if value not in (None, "", []) and not item.get(key):
                        item[key] = value
        for item in agents:
            version_id = str(item.get("agent_version_id") or "")
            if not version_id or version_id in submitted_by_id:
                continue
            parsed = _parse_dt(item.get("submitted_at"))
            if parsed:
                submitted_by_id[version_id] = parsed
        _fill_missing_elim_races(agents)
        last_submitted_by_hot: dict[str, datetime] = {}
        for item in agents:
            hotkey = str(item.get("miner_hotkey") or "")
            version_id = str(item.get("agent_version_id") or "")
            submitted = submitted_by_id.get(version_id)
            if not hotkey or submitted is None:
                continue
            previous = last_submitted_by_hot.get(hotkey)
            if previous is None or submitted > previous:
                last_submitted_by_hot[hotkey] = submitted
        wallet_names = {ss58: label for ss58, (label, _created) in wallet.items()}
        wallet_created = {ss58: created for ss58, (_label, created) in wallet.items()}
        key_names = {
            str(item.get("ss58") or ""): str(item.get("nickname") or "").strip()
            for item in mine
            if item.get("kind") == store.KIND_HOT and str(item.get("ss58") or "")
        }
        standings = _safe_standings()
        standing_rows = [
            row for row in (standings.get("rows") or []) if isinstance(row, dict)
        ]
        q_by_version = {
            str(row.get("agent_version_id") or ""): row.get("qualifying_score")
            for row in standing_rows
            if row.get("agent_version_id")
        }
        r_by_version = {
            str(row.get("agent_version_id") or ""): row.get("race_score")
            for row in standing_rows
            if row.get("agent_version_id")
        }
        margin_by_version = {
            str(row.get("agent_version_id") or ""): row.get("race_margin")
            for row in standing_rows
            if row.get("agent_version_id")
        }
        new_mech_ids, last_old_by_id = _new_mechanism_membership()
        new_mech_ids.update(vid for vid in q_by_version if vid)
        cold_from_standings = {
            str(row.get("miner_hotkey") or ""): str(row.get("coldkey") or "")
            for row in standing_rows
            if row.get("miner_hotkey") and row.get("coldkey")
        }
        raced_hots = {
            str(row.get("miner_hotkey") or "")
            for row in standing_rows
            if row.get("miner_hotkey")
        }
        raced_hots.update(
            str(item.get("miner_hotkey") or "")
            for item in agents
            if item.get("miner_hotkey") and item.get("agent_version_id")
        )
        try:
            from .mongo import get_db as _mongo_db

            for table in _mongo_db().race_tables.find({}, {"rows.miner_hotkey": 1}):
                for row in table.get("rows") or []:
                    if isinstance(row, dict) and row.get("miner_hotkey"):
                        raced_hots.add(str(row.get("miner_hotkey") or ""))
        except Exception:
            pass

        def _coldkey_for(hotkey: str, extra: object = "") -> str:
            neuron = by_hot.get(hotkey) or {}
            prior = remembered.get(hotkey) or {}
            return str(
                neuron.get("coldkey")
                or prior.get("coldkey")
                or wallet_colds.get(hotkey)
                or cold_from_standings.get(hotkey)
                or extra
                or ""
            )

        def _is_deregistered(hotkey: str, uid: object = None) -> bool:
            if uid is not None:
                return False
            prior = remembered.get(hotkey) or {}
            return bool(
                prior.get("was_registered")
                or prior.get("uid") is not None
                or hotkey in raced_hots
            )

        def _ever_on_subnet(hotkey: str) -> bool:
            if not hotkey:
                return False
            if hotkey in by_hot:
                return True
            prior = remembered.get(hotkey) or {}
            return bool(
                prior.get("was_registered")
                or prior.get("uid") is not None
                or hotkey in raced_hots
            )

        pinned_hots = {
            str(item.get("miner_hotkey") or "")
            for item in agents
            if item.get("miner_hotkey")
            and (
                item.get("is_active_qualifier")
                or item.get("is_selected_for_race")
                or str(item.get("agent_version_id") or "") in q_by_version
            )
        }
        seen: set[str] = set()
        rows = []
        for item in agents:
            version_id = str(item.get("agent_version_id") or "")
            if version_id in seen:
                continue
            if version_id:
                seen.add(version_id)
            hotkey = str(item.get("miner_hotkey") or "")
            neuron = by_hot.get(hotkey) or {}
            prior = remembered.get(hotkey) or {}
            submitted = submitted_by_id.get(version_id)
            latest_submitted = last_submitted_by_hot.get(hotkey)
            ends = next_allowed.get(hotkey)
            if ends is None and latest_submitted:
                ends = latest_submitted + COOLDOWN
            stored_ends = stored_next_allowed.get(hotkey)
            if stored_ends and (ends is None or stored_ends > ends):
                ends = stored_ends
            q_score = _agent_q_score(item, q_by_version.get(version_id))
            eliminated_race = _race_number(item.get("eliminated_in_race_number")) or (
                _eliminated_race_from_text(item.get("status"))
            )
            old_elim = _old_mechanism_elim_race(
                item, version_id, new_mech_ids, last_old_by_id
            )
            if old_elim:
                eliminated_race = eliminated_race or old_elim
                item["eliminated_in_race_number"] = eliminated_race
            on_current = bool(version_id and version_id in q_by_version)
            deregistered = _is_deregistered(hotkey, neuron.get("uid"))
            pinned = bool(item.get("pinned"))
            dropped = (
                not on_current
                and not pinned
                and not eliminated_race
                and not item.get("eliminated_at")
                and (
                    _below_threshold(item)
                    or _q_beats_threshold(q_score, standings.get("qualifying_threshold"))
                    is False
                )
            )
            if eliminated_race or item.get("eliminated_at"):
                pinnable = False
            elif dropped:
                pinned = False
                pinnable = False
            else:
                pinnable = not pinned
            status = _format_agent_status(
                item,
                _race_number(standings.get("race_number")),
                q_score,
                standings.get("qualifying_threshold"),
                sibling_pinned=bool(
                    hotkey
                    and hotkey in pinned_hots
                    and not item.get("is_active_qualifier")
                    and not item.get("is_selected_for_race")
                    and not pinned
                ),
                in_current_race=bool(
                    version_id in q_by_version
                    or item.get("is_active_qualifier")
                    or item.get("is_selected_for_race")
                ),
                pinned=pinned,
            )
            if old_elim:
                status = _eliminated_status(eliminated_race)
                pinned = False
                pinnable = False
                on_current = False
                item["is_active_qualifier"] = False
                item["is_selected_for_race"] = False
            eliminated_race = eliminated_race or _eliminated_race_from_text(status)
            rows.append(
                {
                    "agent_version_id": version_id,
                    "agent_name": item.get("agent_name") or "",
                    "version_number": item.get("version_number"),
                    "miner_hotkey": hotkey,
                    "hotkey_name": wallet_names.get(hotkey)
                    or key_names.get(hotkey)
                    or prior.get("name")
                    or "",
                    "coldkey": _coldkey_for(hotkey),
                    "uid": neuron.get("uid"),
                    "deregistered": deregistered,
                    "qualifying_score": q_score,
                    "race_score": r_by_version.get(version_id)
                    or _as_score(item.get("race_score")),
                    "margin": margin_by_version.get(version_id),
                    "is_active_qualifier": bool(item.get("is_active_qualifier") or on_current),
                    "in_current_race": on_current,
                    "pinned": pinned,
                    "pinnable": pinnable,
                    "eliminated_in_race_number": eliminated_race,
                    "status": status,
                    "submitted_at": submitted.isoformat() if submitted else None,
                    "cooldown_ends_at": ends.isoformat() if ends else None,
                }
            )
        rows = [row for row in rows if row.get("agent_name")]
        _enforce_single_pin(
            rows,
            standings.get("qualifying_threshold"),
            set(q_by_version),
            standings.get("race_number"),
        )
        current_race = _race_number(standings.get("race_number"))
        threshold = standings.get("qualifying_threshold")
        for row in rows:
            if row.get("eliminated_in_race_number") or "Eliminated" in str(
                row.get("status") or ""
            ):
                row["pinnable"] = False
                continue
            dropped = (
                not row.get("in_current_race")
                and not row.get("pinned")
                and (
                    str(row.get("status") or "") == "Dropped"
                    or _q_beats_threshold(row.get("qualifying_score"), threshold) is False
                )
            )
            if dropped:
                row["status"] = "Dropped"
                row["pinned"] = False
                row["pinnable"] = False
                continue
            if (
                row.get("in_current_race")
                or row.get("pinned")
                or row.get("is_active_qualifier")
                or _status_is_current(row.get("status"))
            ):
                if row.get("in_current_race") or row.get("pinned"):
                    row["status"] = _race_status_label("Qualifying In", current_race)
                row["pinnable"] = False
            elif _status_is_new(row.get("status"), row.get("submitted_at")):
                row["pinnable"] = True
            else:
                row["pinnable"] = False
        def _submitted_ts(row: dict) -> float:
            parsed = _parse_dt(row.get("submitted_at"))
            return parsed.timestamp() if parsed else 0.0

        groups: dict[str, list[dict]] = {}
        group_order: list[str] = []
        for row in rows:
            key = str(row.get("miner_hotkey") or "")
            if key not in groups:
                group_order.append(key)
                groups[key] = []
            groups[key].append(row)
        group_order.sort(
            key=lambda hot: (
                -(wallet_created.get(hot, 0)),
                str((groups[hot][0] if groups[hot] else {}).get("hotkey_name") or ""),
                hot,
            )
        )
        ordered: list[dict] = []
        for hot in group_order:
            group = groups[hot]
            group.sort(
            key=lambda row: (
                    -_submitted_ts(row),
                    -(row.get("version_number") or 0),
                    str(row.get("agent_name") or "").lower(),
                )
            )
            ordered.extend(group)
        rows = ordered
        kept_hots = {
            str(row.get("miner_hotkey") or "")
            for row in rows
            if row.get("miner_hotkey")
        }
        store.delete_my_hotkeys(
            (set(wallet) | set(remembered) | set(saved_hots)) - kept_hots
        )
        store.save_my_hotkeys(
            [
                {
                    "ss58": str(row.get("miner_hotkey") or ""),
                    "coldkey": str(row.get("coldkey") or ""),
                    "name": str(row.get("hotkey_name") or ""),
                    "uid": row.get("uid"),
                    "was_registered": bool(
                        row.get("uid") is not None
                        or row.get("deregistered")
                        or (remembered.get(str(row.get("miner_hotkey") or "")) or {}).get(
                            "was_registered"
                        )
                        or (remembered.get(str(row.get("miner_hotkey") or "")) or {}).get("uid")
                        is not None
                    ),
                }
                for row in rows
                if row.get("miner_hotkey")
            ]
        )
        if any(row.get("agent_name") for row in rows):
            store.save_my_agent_snapshot(rows)
        payload = {
            "rows": rows,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "complete": _payload_has_agents({"rows": rows}),
        }
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        with _lock:
            if _cache and _cache[1] == mine_key:
                return _cache[2]
        return payload

    with _lock:
        _cache = (time.monotonic(), mine_key, payload)
    return payload
