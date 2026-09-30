import json
import math
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import store
from .network import USER_AGENT
from .neurons import get_registered_uids
from .owners import resolve_missing_owners

CACHE_SECONDS = 10
ORO_BASE = "https://api.oroagents.com/v1/public"

_lock = threading.Lock()
_cache: tuple[float, dict] | None = None
_progress_lock = threading.Lock()
_progress_active = False
_progress_race_number: int | None = None


def _fetch_any(url: str, timeout: float = 12, *, quick: bool = False):
    last_error: Exception | None = None
    attempts = 2 if quick else 5
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429:
                if quick:
                    raise
                time.sleep(4 * (attempt + 1))
                continue
            if exc.code in {500, 502, 503} and attempt < attempts - 1:
                time.sleep(0.4 if quick else 0.6 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            if quick:
                raise
            time.sleep(0.5 * (attempt + 1))
    if last_error:
        raise last_error
    return None


def _fetch_json(url: str, timeout: float = 12, *, quick: bool = False) -> dict:
    payload = _fetch_any(url, timeout=timeout, quick=quick)
    return payload if isinstance(payload, dict) else {}


def _empty() -> dict:
    return {
        "suite_id": None,
        "suite_version": None,
        "race_number": None,
        "race_status": None,
        "qualifying_closes_at": None,
        "qualifying_threshold": None,
        "race_threshold": None,
        "qualifier_count": None,
        "top_agent_name": None,
        "top_hotkey": None,
        "top_score": None,
        "tao_per_day": None,
        "usd_per_day": None,
        "updated_at": None,
    }


def get_current_oro() -> dict:
    global _cache
    now_mono = time.monotonic()
    with _lock:
        if _cache and now_mono - _cache[0] < CACHE_SECONDS:
            return _cache[1]

    payload = _empty()
    try:
        race_wrap = _overview_race_wrap(
            _fetch_json(f"{ORO_BASE}/races/current", timeout=8, quick=True),
            timeout=8,
            quick=True,
        )
        race = race_wrap.get("race") if isinstance(race_wrap.get("race"), dict) else race_wrap
        top: dict = {}
        try:
            top = _fetch_json(f"{ORO_BASE}/top", timeout=8, quick=True)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
            top = {}
        payload.update(
            {
                "race_number": race.get("race_number"),
                "race_status": race.get("status"),
                "qualifying_closes_at": race.get("qualifying_closes_at"),
                "qualifying_threshold": race.get("qualifying_threshold"),
                "race_threshold": (
                    _current_race_field_anchor(race, race_wrap.get("qualifiers") or [])
                    if str(race.get("status") or "").upper() in _RACE_SCORED_STATUS
                    else _as_float(top.get("challenge_threshold") or race.get("challenge_threshold"))
                ),
                "qualifier_count": race.get("qualifier_count"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        if payload.get("race_threshold") is None:
            stored = store.load_current_standings() or {}
            if (
                stored.get("race_threshold") is not None
                and stored.get("race_number") == payload.get("race_number")
            ):
                payload["race_threshold"] = stored.get("race_threshold")
    except Exception:
        with _lock:
            if _cache:
                return _cache[1]
        stored = store.load_current_standings() or {}
        if stored:
            payload.update(
                {
                    "race_number": stored.get("race_number"),
                    "race_status": stored.get("race_status"),
                    "qualifying_threshold": stored.get("qualifying_threshold"),
                    "race_threshold": stored.get("race_threshold"),
                    "updated_at": stored.get("updated_at"),
                }
            )
        return payload

    with _lock:
        _cache = (time.monotonic(), payload)
    return payload


_standings_lock = threading.Lock()
_standings_cache: tuple[float, dict] | None = None
_standings_refreshing = False
_live_build: dict | None = None
_prev_windows_lock = threading.Lock()
_prev_windows_cache: dict | None = None


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _neuron_coldkeys(hotkeys: list[str] | None = None) -> dict[str, str]:
    owners: dict[str, str] = {}
    try:
        owners.update(store.load_hotkey_owners())
    except Exception:
        pass
    try:
        uids = get_registered_uids()
        for item in uids.get("rows") or []:
            if not isinstance(item, dict):
                continue
            hot = str(item.get("hotkey") or "").strip()
            cold = str(item.get("coldkey") or "").strip()
            if hot and cold:
                owners[hot] = cold
    except Exception:
        pass
    missing = [
        str(hot or "").strip()
        for hot in (hotkeys or [])
        if str(hot or "").strip() and not owners.get(str(hot or "").strip())
    ]
    if missing:
        try:
            owners.update(resolve_missing_owners(missing))
        except Exception:
            pass
    return owners


def _row_as_window(row: dict) -> list[dict]:
    window = row.get("window")
    if isinstance(window, list) and any(
        isinstance(entry, dict) and _window_raw(entry) is not None for entry in window
    ):
        return [entry for entry in window if isinstance(entry, dict)]
    rebuilt: list[dict] = []
    for point in row.get("previous") or []:
        if not isinstance(point, dict):
            continue
        rebuilt.append({"race_number": point.get("race_number"), "raw_score": point.get("score")})
    for part in row.get("margins") or []:
        if not isinstance(part, dict):
            continue
        number = _race_num(part.get("race_number"))
        score = _as_float(part.get("score"))
        if number is None or score is None:
            continue
        entry = next((item for item in rebuilt if item.get("race_number") == number), None)
        if entry is None:
            entry = {"race_number": number}
            rebuilt.append(entry)
        # Never override a raw score with a previously displayed margin delta —
        # those can be wrong after a field-anchor correction.
        if entry.get("delta") is None and _window_raw(entry) is None:
            entry["delta"] = score / 100.0
    return rebuilt


def _suite_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _resolve_current_suite_id(current_id: str = "") -> int | None:
    """Suite of the live current race — priors must come from this suite only."""
    suite = _suite_int((_official_current_meta or {}).get("suite_id"))
    if suite is not None:
        return suite
    race_id = str(current_id or (_official_current_meta or {}).get("race_id") or "")
    if race_id:
        try:
            summary = store.load_race_summary(race_id) or {}
            suite = _suite_int(summary.get("suite_id"))
            if suite is not None:
                return suite
        except Exception:
            pass
    try:
        wrap = _fetch_json(f"{ORO_BASE}/races/current", timeout=8, quick=True)
        race = wrap.get("race") if isinstance(wrap.get("race"), dict) else wrap
        if isinstance(race, dict):
            _set_official_current_meta(race)
            return _suite_int(race.get("suite_id"))
    except Exception:
        pass
    return None


_prior_meta_cache: tuple[float, str, int | None, list[dict]] | None = None
_PRIOR_META_CACHE_SECONDS = 45.0


def _suite_for_race_id(race_id: str, summaries: dict[str, dict] | None = None) -> int | None:
    race_id = str(race_id or "")
    if not race_id:
        return None
    if summaries and race_id in summaries:
        return _suite_int((summaries.get(race_id) or {}).get("suite_id"))
    try:
        summary = store.load_race_summary(race_id) or {}
        return _suite_int(summary.get("suite_id"))
    except Exception:
        return None


def _latest_finished_prior_meta(current_id: str = "", limit: int = 2) -> list[dict]:
    """Newest finished races in the *current suite* (newest first).

    Suite resets reuse race_number; a freshly touched table from an older suite
    (e.g. suite-142 race 5 while live is suite-144 race 4) must not become a prior.
    """
    global _prior_meta_cache
    current_id = str(current_id or "")
    suite = _resolve_current_suite_id(current_id)
    now_mono = time.monotonic()
    cached = _prior_meta_cache
    if (
        cached
        and now_mono - cached[0] < _PRIOR_META_CACHE_SECONDS
        and cached[1] == current_id
        and cached[2] == suite
        and len(cached[3]) >= limit
    ):
        return cached[3][:limit]

    out: list[dict] = []
    seen_ids: set[str] = set()

    def _take(race_id: str, number: int | None, row_suite: int | None = None) -> None:
        nonlocal out
        if number is None or not race_id or race_id == current_id or race_id in seen_ids:
            return
        if suite is not None and row_suite is not None and row_suite != suite:
            return
        if suite is not None and row_suite is None:
            # Unknown suite: only accept when we cannot filter yet (filled below).
            return
        seen_ids.add(race_id)
        out.append({"race_number": number, "race_id": race_id, "suite_id": row_suite})

    # 1) ORO history is suite-ordered (current suite first).
    try:
        history = _fetch_json(f"{ORO_BASE}/races/history?limit=12", timeout=10, quick=True)
        races = history.get("races") if isinstance(history, dict) else None
        if isinstance(races, list):
            for hist in races:
                if not isinstance(hist, dict):
                    continue
                race_id = str(hist.get("race_id") or "")
                number = _race_num(hist.get("race_number"))
                row_suite = _suite_int(hist.get("suite_id"))
                if suite is None and row_suite is not None:
                    # First history row defines the live suite when meta was empty.
                    suite = row_suite
                _take(race_id, number, row_suite)
                if len(out) >= limit:
                    _prior_meta_cache = (now_mono, current_id, suite, out[:limit])
                    return out[:limit]
    except Exception:
        pass

    # 2) Local race tables by updated_at, filtered to the current suite via summaries.
    summaries: dict[str, dict] = {}
    try:
        summaries = store.load_all_race_summaries() or {}
    except Exception:
        summaries = {}
    try:
        from api.store import get_db

        cursor = get_db().race_tables.find(
            {},
            {"race_id": 1, "race_number": 1, "updated_at": 1, "_id": 1},
        ).sort("updated_at", -1)
    except Exception:
        cursor = []
    for row in cursor:
        if not isinstance(row, dict):
            continue
        race_id = str(row.get("race_id") or row.get("_id") or "")
        number = _race_num(row.get("race_number"))
        row_suite = _suite_for_race_id(race_id, summaries)
        if suite is not None and row_suite is None:
            # Probe ORO once for missing suite so we do not skip true suite peers.
            try:
                wrap = _fetch_json(f"{ORO_BASE}/races/{race_id}", timeout=6, quick=True)
                race = wrap.get("race") if isinstance(wrap.get("race"), dict) else {}
                row_suite = _suite_int(race.get("suite_id"))
                if row_suite is not None:
                    try:
                        store.save_race_summary(
                            {
                                "race_id": race_id,
                                "race_number": number,
                                "suite_id": row_suite,
                                "status": race.get("status"),
                            }
                        )
                    except Exception:
                        pass
            except Exception:
                row_suite = None
        if suite is None:
            # No suite known: keep updated_at order (legacy fallback).
            if number is None or not race_id or race_id == current_id or race_id in seen_ids:
                continue
            seen_ids.add(race_id)
            out.append({"race_number": number, "race_id": race_id, "suite_id": row_suite})
        else:
            _take(race_id, number, row_suite)
        if len(out) >= limit:
            break

    result = out[:limit]
    _prior_meta_cache = (now_mono, current_id, suite, result)
    return result


def _latest_finished_prior_numbers(
    current_number: object = None, current_id: str = "", limit: int = 2
) -> list[int]:
    """Race numbers of the two latest finished races (newest first), for WIN/Margin.

    Never returns the live current race_number — that slot is filled separately.
    """
    current = _race_num(current_number)
    current_id = str(current_id or "")
    with _prev_windows_lock:
        cached = _prev_windows_cache or {}
        if cached.get("for_current") == current or current is None:
            cached_nums = [
                _race_num(value)
                for value in (cached.get("prior_numbers") or [])
            ]
            cached_nums = [
                number
                for number in cached_nums
                if number is not None and (current is None or number != current)
            ]
            meta = list(cached.get("prior_meta") or [])
            if len(cached_nums) >= limit and meta:
                return cached_nums[:limit]
    out: list[int] = []
    for item in _latest_finished_prior_meta(current_id, limit=max(limit + 2, 4)):
        number = _race_num(item.get("race_number"))
        if number is None:
            continue
        if current is not None and number == current:
            continue
        if number in out:
            continue
        out.append(int(number))
        if len(out) >= limit:
            break
    return out[:limit]


def _finished_race_id_for_number(number: int, suite_id: int | None = None) -> str:
    """Race_id of the finished suite race with this race_number (newest match)."""
    suite = suite_id if suite_id is not None else _resolve_current_suite_id()
    for item in _latest_finished_prior_meta("", limit=12):
        if _race_num(item.get("race_number")) != number:
            continue
        if suite is not None and _suite_int(item.get("suite_id")) not in (None, suite):
            continue
        return str(item.get("race_id") or "")
    return ""


def _snapshot_standings_into_race_table(payload: dict) -> None:
    """Persist LIVE_RANKING / finished standings rows into race_tables when empty.

    Overview WIN/Overall need prior race_id tables; the poller sometimes advances
    the live race_id before the finished table is written.
    """
    number = _race_num(payload.get("race_number"))
    status = _status_upper(payload.get("race_status") or payload.get("status"))
    if number is None or status not in {
        "LIVE_RANKING",
        "RACE_COMPLETE",
        "COMPLETED",
        "FINISHED",
        "CLOSED",
    }:
        return
    rows = [
        dict(row)
        for row in (payload.get("rows") or [])
        if isinstance(row, dict) and _as_float(row.get("race_score")) is not None
    ]
    if not rows:
        return
    suite = _suite_int(payload.get("suite_id")) or _resolve_current_suite_id(
        str(payload.get("race_id") or "")
    )
    race_id = _finished_race_id_for_number(number, suite)
    if not race_id:
        # Fall back to payload race_id only when it is not already the next live race.
        candidate = str(payload.get("race_id") or "")
        official_id = str((_official_current_meta or {}).get("race_id") or "")
        if candidate and candidate != official_id:
            race_id = candidate
    if not race_id:
        return
    try:
        existing = store.load_race_table(race_id) or {}
    except Exception:
        existing = {}
    if existing.get("rows"):
        return
    field = _as_float(payload.get("race_threshold")) or _top_half_anchor(rows, number)
    try:
        store.save_race_table(
            {"race_id": race_id, "race_number": number, "rows": rows},
            False,
        )
        if field is not None:
            store.save_race_thresholds({number: field})
            store.save_race_summary(
                {
                    "race_id": race_id,
                    "race_number": number,
                    "suite_id": suite,
                    "status": "RACE_COMPLETE",
                    "race_threshold": field,
                }
            )
    except Exception:
        pass


def _heal_overview_identity(payload: dict) -> dict:
    """Adopt ORO /races/current identity when Mongo standings lag a race transition."""
    if not isinstance(payload, dict) or not (payload.get("rows") or []):
        return payload
    race: dict = {}
    try:
        wrap = _fetch_json(f"{ORO_BASE}/races/current", timeout=8, quick=True)
        race = wrap.get("race") if isinstance(wrap.get("race"), dict) else wrap
        if isinstance(race, dict):
            _set_official_current_meta(race)
    except Exception:
        race = dict(_official_current_meta or {})
    if not isinstance(race, dict):
        return payload
    official_n = _race_num(race.get("race_number"))
    official_id = str(race.get("race_id") or "")
    official_status = race.get("status")
    suite = _suite_int(race.get("suite_id"))
    if official_n is None:
        return payload
    out = dict(payload)
    stored_n = _race_num(out.get("race_number"))
    stored_id = str(out.get("race_id") or "")
    stored_status = _status_upper(out.get("race_status") or out.get("status"))
    moved = stored_n != official_n or (
        official_id and stored_id and stored_id != official_id and stored_n == official_n
    )
    # Stuck LIVE_RANKING while ORO already opened the next QUALIFYING race.
    stuck_live = (
        _is_qualifying_only(official_status)
        and stored_status == "LIVE_RANKING"
        and (stored_n != official_n or (official_id and stored_id == official_id))
    )
    if stuck_live or (moved and _is_qualifying_only(official_status)):
        # Keep finished scores for WIN/Overall before clearing the live columns.
        _snapshot_standings_into_race_table(out)
        global _prev_windows_cache, _prior_meta_cache
        _prev_windows_cache = None
        _prior_meta_cache = None
        out["race_number"] = official_n
        if official_id:
            out["race_id"] = official_id
        if suite is not None:
            out["suite_id"] = suite
        out["race_status"] = official_status
        out["race_threshold"] = None
        rows = []
        for row in out.get("rows") or []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item["race_score"] = None
            item["race_margin"] = None
            item["race_rank"] = None
            item["overall_score"] = None
            item["weighted_score"] = None
            rows.append(item)
        out["rows"] = rows
        try:
            store.save_current_standings(out)
        except Exception:
            pass
        return out
    if official_id and not stored_id:
        out["race_id"] = official_id
    if suite is not None and out.get("suite_id") is None:
        out["suite_id"] = suite
    # Still snapshot a completed live-ranking table so priors stay available.
    if stored_status == "LIVE_RANKING":
        _snapshot_standings_into_race_table(out)
    return out


def _index_anchors_match_official(
    index: dict, anchors_by_number: dict[int, float], prior_numbers: list[int]
) -> bool:
    """False when cached window entries still carry a stale field for a prior race."""
    if not prior_numbers:
        return True
    wanted = {number: anchors_by_number.get(number) for number in prior_numbers}
    if any(value is None for value in wanted.values()):
        return False
    checked = 0
    for window in (index or {}).values():
        if not isinstance(window, list):
            continue
        for entry in window:
            if not isinstance(entry, dict):
                continue
            number = _race_num(entry.get("race_number"))
            if number not in wanted:
                continue
            entry_anchor = _as_float(entry.get("anchor"))
            official = wanted.get(number)
            if entry_anchor is None or official is None:
                return False
            if abs(entry_anchor - official) > 1e-6:
                return False
            checked += 1
    return checked > 0


def _warm_prior_windows_local(current_number: object, current_id: str = "") -> None:
    """Fill WIN/Margin priors from stored race tables without waiting on live ORO."""
    global _prev_windows_cache
    current = _race_num(current_number)
    # Discover priors from local tables first (ignore a stale cache for_current).
    meta = _latest_finished_prior_meta(current_id, limit=2)
    priors = [int(item["race_number"]) for item in meta if item.get("race_number") is not None]
    prior_ids = [str(item.get("race_id") or "") for item in meta if item.get("race_id")]
    with _prev_windows_lock:
        cached = _prev_windows_cache or {}
        by_id = cached.get("anchors_by_id") or {}
        cached_anchors = dict(cached.get("anchors") or {})
        for rid, number in (
            (str(item.get("race_id") or ""), _race_num(item.get("race_number")))
            for item in meta
        ):
            if number is None or not rid:
                continue
            field = _as_float(by_id.get(rid))
            if field is not None:
                cached_anchors[number] = field
        if (
            cached.get("for_current") == current
            and list(cached.get("prior_numbers") or []) == priors
            and list(cached.get("prior_meta") or []) == meta
            and all(rid in by_id and by_id.get(rid) is not None for rid in prior_ids)
            and _index_anchors_match_official(
                cached.get("by_name_version_hotkey") or {}, cached_anchors, priors
            )
            and (
                not priors
                or all(
                    _prior_race_coverage(cached.get("by_name_version_hotkey") or {}, number) > 0
                    or _prior_race_coverage(cached.get("by_version") or {}, number) > 0
                    for number in priors
                )
            )
        ):
            return
        by_version = dict(cached.get("by_version") or {}) if cached.get("for_current") == current else {}
        by_name_version_hotkey = (
            dict(cached.get("by_name_version_hotkey") or {})
            if cached.get("for_current") == current
            else {}
        )
        # Drop number-keyed anchors for priors; they may be old-suite top-half values.
        anchors = {}
        if cached.get("for_current") == current:
            for key, value in (cached.get("anchors") or {}).items():
                if key not in priors:
                    anchors[key] = value
        anchors_by_id = dict(cached.get("anchors_by_id") or {})
    try:
        # Keep non-prior thresholds; prior fields come from race_id official anchors.
        stored = store.load_race_thresholds()
        for number in priors:
            stored.pop(number, None)
        anchors = {**stored, **anchors}
    except Exception:
        pass
    _backfill_previous_from_local_tables(
        current,
        anchors,
        by_version,
        by_name_version_hotkey,
        prior_numbers=priors,
        current_id=current_id,
    )
    if by_version or by_name_version_hotkey or anchors or priors:
        with _prev_windows_lock:
            prev = _prev_windows_cache or {}
            merged_by_id = {**anchors_by_id, **dict(prev.get("anchors_by_id") or {})}
            _prev_windows_cache = {
                "for_current": current,
                "by_version": by_version,
                "by_name_version_hotkey": by_name_version_hotkey,
                "anchors": anchors,
                "prior_numbers": priors,
                "prior_meta": meta,
                "anchors_by_id": merged_by_id,
            }


def _strip_stale_prior_points(row: dict, prior_numbers: set[int]) -> dict:
    """Drop stored WIN points for prior race_numbers so old-suite scores cannot leak.

    Suite resets reuse race_number (e.g. race 3 in suite 142 vs suite 144). Mongo
    standings often still carry the older score under the same number.
    """
    if not prior_numbers:
        return row
    out = dict(row)

    def keep(points: object) -> list:
        cleaned: list = []
        for point in points or []:
            if not isinstance(point, dict):
                continue
            number = _race_num(point.get("race_number"))
            if number in prior_numbers:
                continue
            cleaned.append(point)
        return cleaned

    if isinstance(row.get("previous"), list):
        out["previous"] = keep(row.get("previous"))
    if isinstance(row.get("margins"), list):
        out["margins"] = keep(row.get("margins"))
    if isinstance(row.get("window"), list):
        out["window"] = keep(row.get("window"))
    return out


def _ensure_standings_margins(payload: dict) -> dict:
    rows = [dict(row) for row in (payload.get("rows") or []) if isinstance(row, dict)]
    if not rows:
        return payload
    current = payload.get("race_number")
    current_id = str(payload.get("race_id") or "") or str(
        (_official_current_meta or {}).get("race_id") or ""
    )
    suite = _suite_int(payload.get("suite_id")) or _resolve_current_suite_id(current_id)
    if suite is not None and not payload.get("suite_id"):
        payload = {**payload, "suite_id": suite}
    if current_id and not payload.get("race_id"):
        payload = {**payload, "race_id": current_id}
    # Mongo standings often keep previous/margin empty after a suite reset;
    # rehydrate from the two latest finished races on every Overview read.
    _warm_prior_windows_local(current, current_id)
    priors = _latest_finished_prior_numbers(current, current_id)
    prior_set = {number for number in priors if number is not None}
    anchors = _official_field_anchors(current, current_id)
    # Anchors for prior races must come from the latest race_id tables, not a
    # polluted race_number threshold left over from an older suite.
    with _prev_windows_lock:
        cached = _prev_windows_cache or {}
        by_id = cached.get("anchors_by_id") or {}
        for item in cached.get("prior_meta") or []:
            if not isinstance(item, dict):
                continue
            number = _race_num(item.get("race_number"))
            race_id = str(item.get("race_id") or "")
            if number is None or number not in prior_set:
                continue
            field = _as_float(by_id.get(race_id)) if race_id else None
            if field is None:
                field = _as_float((cached.get("anchors") or {}).get(number))
            if field is not None:
                anchors[number] = field
    qualifying = _is_qualifying_only(payload.get("race_status") or payload.get("status"))
    items = []
    for row in rows:
        cleaned = _strip_stale_prior_points(row, prior_set)
        # Lookup (latest race_id tables) is primary so it wins over any leftover.
        window = _merge_window(_lookup_previous_windows(row), _row_as_window(cleaned))
        items.append({**row, "window": window, "race_id": current_id})
    if not anchors:
        anchors = _anchors_from_windows(items)
    filled = []
    for row, item in zip(rows, items):
        out = dict(row)
        race_score = None if qualifying else out.get("race_score")
        scored = {**item, "race_id": current_id}
        out["previous"] = _previous_scores(scored, current, race_score)
        out["margins"] = _margin_parts(scored, current, anchors)
        out["margin"] = _margin_sum(scored, current, anchors)
        out["race_margin"] = None if qualifying else out.get("race_margin")
        filled.append(out)
    return {**payload, "rows": filled}


def _with_key_fields(payload: dict) -> dict:
    payload = _ensure_standings_margins(payload)
    rows = []
    needed: list[str] = []
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        hot = str(item.get("miner_hotkey") or "").strip()
        item["miner_hotkey"] = hot
        item["coldkey"] = str(item.get("coldkey") or "").strip()
        rows.append(item)
        if hot and not item["coldkey"]:
            needed.append(hot)
    owners = _neuron_coldkeys(needed)
    filled: dict[str, str] = {}
    for item in rows:
        hot = item["miner_hotkey"]
        cold = item["coldkey"] or owners.get(hot, "")
        item["coldkey"] = cold
        if hot and cold:
            filled[hot] = cold
    if filled:
        try:
            store.save_hotkey_owners(filled)
        except Exception:
            pass
    out = dict(payload)
    out["rows"] = rows
    return out


def _empty_standings() -> dict:
    return {
        "race_number": None,
        "race_status": None,
        "race_threshold": None,
        "qualifying_threshold": None,
        "total": 0,
        "rows": [],
        "updated_at": None,
        "finished_race": None,
    }


def _int_or_none(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _item_race_rank(item: dict) -> int | None:
    return _int_or_none(item.get("race_rank"))


_RACE_SCORED_STATUS = {
    "RACE_RUNNING",
    "RACE_COMPLETE",
    "LIVE_RANKING",
    "COMPLETED",
    "FINISHED",
    "CLOSED",
    "RUNNING",
    "IN_PROGRESS",
}
_QUALIFYING_STATUS = {"QUALIFYING", "QUALIFYING_OPEN"}
_FETCH_ERRORS = (
    urllib.error.HTTPError,
    urllib.error.URLError,
    TimeoutError,
    ValueError,
    OSError,
    json.JSONDecodeError,
)


def _window_list(item: dict) -> list[dict]:
    window = item.get("window")
    if isinstance(window, list):
        return [entry for entry in window if isinstance(entry, dict)]
    return []


def _window_raw_for_race(item: dict, race_number: int | None) -> float | None:
    current = _race_num(race_number)
    if current is None:
        return None
    for entry in _window_list(item):
        if _race_num(entry.get("race_number")) != current:
            continue
        raw = _as_float(entry.get("raw_score"))
        if raw is not None:
            return raw
    return None


def _score_window(item: dict) -> list[dict]:
    window = _window_list(item)
    if window:
        return window
    points = item.get("races")
    if not isinstance(points, list):
        return []
    rows = []
    for point in points:
        if not isinstance(point, dict) or point.get("race_number") is None:
            continue
        raw = _as_float(point.get("raw_score") if point.get("raw_score") is not None else point.get("score"))
        if raw is None:
            continue
        rows.append({"race_number": point.get("race_number"), "raw_score": raw})
    return rows


def _item_race_score(
    item: dict,
    current_race: int | None,
    status: object = None,
    live: float | None = None,
) -> float | None:
    if str(status or "").upper() not in _RACE_SCORED_STATUS:
        return None
    current = _window_raw_for_race(item, current_race)
    if current is not None:
        return current
    if live is not None:
        return live
    score = _as_float(item.get("race_score"))
    if score is not None:
        return score
    if _window_list(item) or _score_window(item):
        return None
    return None


def _current_overall_score(item: dict, source: dict, current_race: int | None) -> float | None:
    score = _as_float(item.get("weighted_score"))
    if score is not None:
        return score
    current = _race_num(current_race)
    if current is None:
        return None
    for entry in (*_window_list(source), *_window_list(item)):
        if _race_num(entry.get("race_number")) != current:
            continue
        for key in ("weighted_score", "overall_score"):
            value = _as_float(entry.get(key))
            if value is not None:
                return value
    return None


def _collect_row_race_scores(row: dict) -> dict[int, float]:
    scores: dict[int, float] = {}
    for key in ("previous", "races"):
        for point in row.get(key) or []:
            if not isinstance(point, dict):
                continue
            number = _race_num(point.get("race_number"))
            score = _as_float(
                point.get("score") if point.get("score") is not None else point.get("raw_score")
            )
            if number is not None and score is not None:
                scores[number] = score
    for entry in _window_list(row):
        number = _race_num(entry.get("race_number"))
        score = _window_raw(entry)
        if number is not None and score is not None:
            scores[number] = score
    return scores


def _history_scores_by_version(
    current: int, current_id: str = ""
) -> dict[str, dict[int, float]]:
    window = _overall_window_numbers(current, current_id)
    wanted = list(window)
    by_id: dict[str, dict[int, float]] = {}
    tables: dict[int, dict] = {}
    # Prefer race_id tables from prior meta (suite-safe).
    try:
        for item in _latest_finished_prior_meta(current_id, limit=4):
            number = _race_num(item.get("race_number"))
            race_id = str(item.get("race_id") or "")
            if number is None or number not in wanted or not race_id:
                continue
            table = store.load_race_table(race_id)
            if isinstance(table, dict) and (table.get("rows") or []):
                tables[number] = table
    except Exception:
        pass
    missing = [number for number in wanted if number not in tables]
    if missing:
        try:
            loaded = store.load_race_tables_by_numbers(missing)
        except Exception:
            loaded = {}
        if isinstance(loaded, dict):
            tables.update(loaded)
    for number, table in tables.items():
        for row in table.get("rows") or []:
            if not isinstance(row, dict):
                continue
            version_id = str(row.get("agent_version_id") or "")
            if not version_id:
                continue
            dest = by_id.setdefault(version_id, {})
            score = _as_float(row.get("race_score"))
            if score is not None:
                dest[number] = score
            for point in row.get("races") or []:
                if not isinstance(point, dict):
                    continue
                race_n = _race_num(point.get("race_number"))
                raw = _as_float(
                    point.get("score") if point.get("score") is not None else point.get("raw_score")
                )
                if race_n in wanted and raw is not None:
                    dest[race_n] = raw
    return by_id


def _difficulty_adjusted_overall(
    scores: dict[int, float],
    current: int,
    anchors: dict[int, float],
    window_numbers: list[int] | None = None,
) -> float | None:
    field = _as_float(anchors.get(current))
    if field is None:
        return None
    if not window_numbers:
        window_numbers = [current]
        for number in _latest_finished_prior_numbers(current, limit=2):
            if number != current and number not in window_numbers:
                window_numbers.append(number)
            if len(window_numbers) >= 3:
                break
    slots: list[int | None] = list(window_numbers[:3])
    while len(slots) < 3:
        slots.append(None)
    total = 0.0
    for number in slots:
        if number is None:
            total += field
            continue
        raw = _as_float(scores.get(number))
        if raw is None:
            total += field
            continue
        race_field = _as_float(anchors.get(number))
        total += field + (raw - race_field) if race_field is not None else raw
    return round(total / 3.0, 4)


def _overall_window_numbers(current: int, current_id: str = "") -> list[int]:
    """Current race plus the two latest finished priors (chronological suite peers)."""
    window = [current]
    for number in _latest_finished_prior_numbers(current, current_id, limit=2):
        if number != current and number not in window:
            window.append(number)
        if len(window) >= 3:
            break
    return window


def _overall_ready(status: object) -> bool:
    return _status_upper(status) in {
        "LIVE_RANKING",
        "RACE_COMPLETE",
        "COMPLETED",
        "FINISHED",
        "CLOSED",
    }


def _fill_standings_overall(payload: dict) -> dict:
    rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
    current = _race_num(payload.get("race_number"))
    current_id = str(payload.get("race_id") or "")
    if not rows or current is None:
        return payload
    if not _overall_ready(payload.get("race_status")):
        changed = False
        for row in rows:
            if row.get("overall_score") is not None:
                row["overall_score"] = None
                changed = True
        if changed:
            payload["rows"] = rows
        return payload
    try:
        anchors = dict(store.load_race_thresholds())
    except Exception:
        anchors = {}
    # Prefer race_id official fields for the overall window.
    window_nums = _overall_window_numbers(current, current_id)
    with _prev_windows_lock:
        cached = _prev_windows_cache or {}
        by_id = cached.get("anchors_by_id") or {}
        for item in cached.get("prior_meta") or []:
            if not isinstance(item, dict):
                continue
            number = _race_num(item.get("race_number"))
            race_id = str(item.get("race_id") or "")
            if number is None or number not in window_nums:
                continue
            field = _as_float(by_id.get(race_id)) if race_id else None
            if field is None:
                field = _as_float((cached.get("anchors") or {}).get(number))
            if field is not None:
                anchors[number] = field
    field = _as_float(payload.get("race_threshold")) or _stored_race_anchor(current)
    if field is not None:
        anchors[current] = field
    if current not in anchors:
        # Last resort: top-half of current standings race scores.
        field = _top_half_anchor(rows, current)
        if field is not None:
            anchors[current] = field
    if current not in anchors:
        return payload
    # Ensure prior race fields exist for window peers.
    for number in window_nums:
        if number == current or number in anchors:
            continue
        race_id = _finished_race_id_for_number(number)
        if race_id:
            got = _official_field_for_race_id(race_id, number, quick=True)
            if got is not None:
                anchors[number] = got
    history = _history_scores_by_version(current, current_id)
    changed = False
    for row in rows:
        official = _as_float(row.get("weighted_score"))
        if official is not None:
            if _as_float(row.get("overall_score")) != official:
                row["overall_score"] = official
                changed = True
            continue
        version_id = str(row.get("agent_version_id") or "")
        scores = {**(history.get(version_id) or {}), **_collect_row_race_scores(row)}
        # Prefer name+version+hotkey prior lookup scores when version_id history is thin.
        for entry in _lookup_previous_windows(row):
            number = _race_num(entry.get("race_number"))
            raw = _window_raw(entry)
            if number is not None and raw is not None:
                scores[number] = raw
        race_score = _as_float(row.get("race_score"))
        if race_score is not None:
            scores[current] = race_score
        overall = _difficulty_adjusted_overall(scores, current, anchors, window_nums)
        if overall is None or _as_float(row.get("overall_score")) == overall:
            continue
        row["overall_score"] = overall
        changed = True
    if changed:
        payload["rows"] = rows
        try:
            store.save_current_standings(payload)
        except Exception:
            pass
    return payload


def _item_current_race_rank(item: dict, status: object) -> int | None:
    if str(status or "").upper() not in _RACE_SCORED_STATUS:
        return None
    return _item_race_rank(item)


def _item_coldkey(item: dict) -> str:
    for key in ("coldkey", "owner", "miner_coldkey", "cold_key", "owner_ss58"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _current_race_agents(qualifiers: object) -> list[dict]:
    rows = []
    seen: set[str] = set()
    if not isinstance(qualifiers, list):
        return rows
    for item in qualifiers:
        if not isinstance(item, dict) or item.get("is_discarded"):
            continue
        version_id = str(item.get("agent_version_id") or "")
        hotkey = str(item.get("miner_hotkey") or "")
        key = version_id or hotkey
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(item)
    return rows


def _race_num(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _entry_is_seed(entry: dict) -> bool:
    if entry.get("is_seed"):
        return True
    return False


def _merge_window(primary: object, secondary: object) -> list[dict]:
    by_num: dict[int, dict] = {}
    for src in (secondary, primary):
        if not isinstance(src, list):
            continue
        for entry in src:
            if not isinstance(entry, dict):
                continue
            number = _race_num(entry.get("race_number"))
            if number is None:
                continue
            old = by_num.get(number, {})
            if src is primary and _entry_is_seed(entry):
                # A newer version often ships seed placeholders for races the
                # miner already finished on an older version_id. Never erase
                # that real score — Overview WIN needs the hotkey history.
                if old and not _entry_is_seed(old) and _window_raw(old) is not None:
                    continue
                by_num[number] = {
                    **old,
                    **entry,
                    "race_number": number,
                    "raw_score": None,
                    "delta": None,
                    "is_seed": True,
                }
                continue
            if _entry_is_seed(old) and (src is not primary or _entry_is_seed(entry)):
                continue
            merged = {**old, **entry, "race_number": number}
            if merged.get("delta") is None and old.get("delta") is not None and not _entry_is_seed(old):
                merged["delta"] = old.get("delta")
            if merged.get("raw_score") is None and old.get("raw_score") is not None and not _entry_is_seed(old):
                merged["raw_score"] = old.get("raw_score")
            by_num[number] = merged
    return list(by_num.values())


def _window_entries(item: dict, current_race: int | None) -> list[dict]:
    window = item.get("window") if isinstance(item.get("window"), list) else []
    current = _race_num(current_race)
    entries: list[dict] = []
    for entry in window:
        if not isinstance(entry, dict):
            continue
        number = _race_num(entry.get("race_number"))
        if number is None or (current is not None and number == current):
            continue
        entries.append({**entry, "race_number": number})
    entries.sort(key=lambda row: row.get("race_number") or 0)
    return entries


def _window_raw(entry: dict) -> float | None:
    if entry.get("raw_score") is not None:
        return _as_float(entry.get("raw_score"))
    return _as_float(entry.get("score"))


def _anchors_from_windows(items: list[dict]) -> dict[int, float]:
    scores: dict[int, list[float]] = {}
    for item in items:
        for entry in _window_list(item):
            number = _race_num(entry.get("race_number"))
            raw = _window_raw(entry)
            if number is None or raw is None:
                continue
            scores.setdefault(number, []).append(raw)
    anchors: dict[int, float] = {}
    for number, values in scores.items():
        values.sort(reverse=True)
        half = values[: max(1, len(values) // 2)]
        anchors[number] = round(sum(half) / len(half), 4)
    return anchors


def _entry_delta(entry: dict, anchors: dict[int, float] | None = None) -> float | None:
    if _entry_is_seed(entry):
        return None
    raw = _window_raw(entry)
    number = _race_num(entry.get("race_number"))
    map_anchor = anchors.get(number) if anchors and number is not None else None
    entry_anchor = _as_float(entry.get("anchor"))
    field = map_anchor if map_anchor is not None else entry_anchor
    # Prefer ORO's own window.delta when it matches the official field (exact
    # platform Margin, e.g. C.RONALDO +12.3). Recompute when the cached delta
    # was built from a stale top-half field.
    oro_delta = _as_float(entry.get("delta"))
    if (
        oro_delta is not None
        and abs(oro_delta) <= 1
        and entry.get("oro_delta")
        and (field is None or raw is None or abs((raw - field) - oro_delta) <= 5e-4)
    ):
        return oro_delta
    if raw is not None and field is not None:
        return raw - field
    if oro_delta is not None and abs(oro_delta) <= 1:
        return oro_delta
    return None


def _prev_pair_entries(item: dict, current_race: int | None) -> list[dict]:
    """Entries for the two latest finished races (oldest of the pair first)."""
    current = _race_num(current_race)
    current_id = str(item.get("race_id") or "")
    priors = [
        number
        for number in _latest_finished_prior_numbers(current, current_id)
        if number != current
    ]
    if not priors:
        return _window_entries(item, None)[-2:]
    # Margin sum order: older prior then newer prior (e.g. race 5 then race 1).
    ordered = list(reversed(priors[:2]))
    by_num: dict[int, dict] = {}
    for entry in _window_list(item):
        number = _race_num(entry.get("race_number"))
        if number is None:
            continue
        by_num[number] = {**entry, "race_number": number}
    return [by_num.get(number) or {"race_number": number} for number in ordered]


def _margin_parts(
    item: dict, current_race: int | None, anchors: dict[int, float] | None = None
) -> list[dict]:
    parts: list[dict] = []
    for entry in _prev_pair_entries(item, current_race):
        delta = _entry_delta(entry, anchors)
        parts.append(
            {
                "race_number": entry.get("race_number"),
                "score": round(delta * 100, 2) if delta is not None else None,
                "_delta": delta,
            }
        )
    return [
        {"race_number": part.get("race_number"), "score": part.get("score")}
        for part in parts
        if part.get("score") is not None
    ]


def _margin_sum(
    item: dict, current_race: int | None, anchors: dict[int, float] | None = None
) -> float | None:
    # Round once on the summed raw deltas so totals match ORO (e.g. C.RONALDO 12.3).
    deltas: list[float] = []
    for entry in _prev_pair_entries(item, current_race):
        delta = _entry_delta(entry, anchors)
        if delta is not None:
            deltas.append(delta)
    if not deltas:
        return None
    return round(sum(deltas) * 100, 2)


def _race_anchor_margin(score: object, anchor: object) -> float | None:
    raw = _as_float(score)
    field = _as_float(anchor)
    if raw is None or field is None:
        return None
    return round((raw - field) * 100, 2)


def _current_race_margin(
    item: dict, current_race: int | None, anchors: dict[int, float] | None = None
) -> float | None:
    current = _race_num(current_race)
    if current is None:
        return None
    window = item.get("window") if isinstance(item.get("window"), list) else []
    for entry in window:
        if not isinstance(entry, dict) or _race_num(entry.get("race_number")) != current:
            continue
        delta = _entry_delta(entry, anchors)
        if delta is None:
            continue
        return round(delta * 100, 2)
    anchor = anchors.get(current) if anchors else None
    return _race_anchor_margin(item.get("race_score"), anchor)


def _name_version_key(agent_name: object, version_number: object) -> str:
    """Agent name + version number (case-sensitive name)."""
    name = str(agent_name or "").strip()
    if not name:
        return ""
    try:
        if version_number is None or version_number == "":
            return ""
        version = int(version_number)
    except (TypeError, ValueError):
        version = str(version_number).strip()
        if not version:
            return ""
        return f"{name}::v{version}"
    return f"{name}::v{version}"


def _name_version_hotkey_key(
    agent_name: object, version_number: object, hotkey: object
) -> str:
    """WIN identity: same agent name + version on the same miner hotkey."""
    nv = _name_version_key(agent_name, version_number)
    hot = str(hotkey or "").strip()
    if not nv or not hot:
        return ""
    return f"{nv}::{hot}"


def _lookup_previous_windows(item: dict) -> list[dict]:
    """Prior-race WIN points for the same version_id or name+version+hotkey."""
    with _prev_windows_lock:
        cached = _prev_windows_cache or {}
    version_id = str(item.get("agent_version_id") or "")
    nvh_key = _name_version_hotkey_key(
        item.get("agent_name"), item.get("version_number"), item.get("miner_hotkey")
    )
    by_version = cached.get("by_version") or {}
    by_nvh = cached.get("by_name_version_hotkey") or {}
    merged: list[dict] = []
    # Exact submission id first, then name+version+hotkey (same miner/version).
    if version_id and version_id in by_version:
        merged = _merge_window(merged, by_version.get(version_id) or [])
    if nvh_key and nvh_key in by_nvh:
        merged = _merge_window(merged, by_nvh.get(nvh_key) or [])
    return merged


def _previous_scores(
    item: dict, current_race: int | None, current_score: float | None = None
) -> list[dict]:
    current = _race_num(current_race)
    by_num: dict[int, float] = {}
    for entry in _window_list(item):
        number = _race_num(entry.get("race_number"))
        if number is None:
            continue
        raw = _as_float(entry.get("raw_score"))
        if raw is None:
            raw = _as_float(entry.get("score"))
        if raw is None:
            continue
        by_num[number] = raw
    if current is None:
        numbers = sorted(by_num, reverse=True)[:3]
        while len(numbers) < 3:
            numbers.append(None)  # type: ignore[arg-type]
        return [
            {
                "race_number": number,
                "score": by_num.get(number) if number is not None else None,
            }
            for number in numbers
        ]
    if current_score is not None:
        by_num[current] = current_score
    # WIN slots: current race, then the two latest finished races (never duplicate current).
    current_id = str(item.get("race_id") or "")
    priors = [
        number
        for number in _latest_finished_prior_numbers(current, current_id)
        if number != current
    ]
    numbers: list[int | None] = [current]
    for number in priors[:2]:
        numbers.append(number)
    while len(numbers) < 3:
        numbers.append(None)
    return [
        {"race_number": number, "score": by_num.get(number) if number is not None else None}
        for number in numbers[:3]
    ]


_LIVE_STATUS = {"RACE_RUNNING", "QUALIFYING", "QUALIFYING_OPEN", "RUNNING", "IN_PROGRESS"}


def _status_upper(value: object) -> str:
    return str(value or "").upper()


def _is_qualifying_only(status: object) -> bool:
    return _status_upper(status) in _QUALIFYING_STATUS


def _overview_display_status(status: object) -> str:
    raw = _status_upper(status)
    if raw in {"RACE_COMPLETE", "COMPLETED", "FINISHED", "CLOSED"}:
        return "RACE_COMPLETE"
    if raw == "LIVE_RANKING":
        return "LIVE_RANKING"
    return str(status or "")


_official_current_meta: dict = {}


def _set_official_current_meta(race: dict | None) -> None:
    global _official_current_meta
    if not isinstance(race, dict):
        return
    _official_current_meta = {
        "race_id": str(race.get("race_id") or ""),
        "race_number": race.get("race_number"),
        "status": race.get("status"),
        "suite_id": race.get("suite_id"),
    }


def _race_finished_with_tops(source: dict | None) -> bool:
    if not isinstance(source, dict):
        return False
    race_id = str(source.get("race_id") or "")
    stored = store.load_race_summary(race_id) if race_id else None
    if stored:
        stored = _apply_stored_leaders(stored)
        if stored.get("overall_agent") and stored.get("race_agent"):
            return True
    if source.get("overall_agent") and source.get("race_agent"):
        return True
    rows = source.get("rows") if isinstance(source.get("rows"), list) else []
    if rows:
        overall_agent, _overall_score = _top_stored_row(rows, "overall_score")
        race_agent, _race_score = _top_stored_row(rows, "race_score")
        if overall_agent and race_agent:
            return True
    return False


def _live_race_payload(source: dict | None) -> dict:
    if not isinstance(source, dict):
        return {}
    race = source.get("race") if isinstance(source.get("race"), dict) else source
    return race if isinstance(race, dict) else {}


def _live_race_agents(source: dict | None) -> list[dict]:
    if not isinstance(source, dict):
        return []
    race = _live_race_payload(source)
    items: list[dict] = []
    for bucket in (source, race):
        for key in ("qualifiers", "rows"):
            value = bucket.get(key)
            if isinstance(value, list):
                items.extend(item for item in value if isinstance(item, dict))
    return items


def _agent_has_race_result(item: dict) -> bool:
    return (
        item.get("race_score") is not None
        or item.get("race_rank") is not None
        or item.get("weighted_score") is not None
    )


def _stored_rankings_tallied(race_id: str = "", number: object = None) -> bool:
    race_id = str(race_id or "")
    want = _race_num(number)
    finished = {"RACE_COMPLETE", "COMPLETED", "FINISHED", "CLOSED"}
    try:
        stored = store.load_current_standings() or {}
    except Exception:
        stored = {}
    stored_n = _race_num(stored.get("race_number"))
    stored_status = _status_upper(stored.get("race_status") or stored.get("status"))
    if (
        stored.get("rows")
        and stored_status in finished
        and (want is None or stored_n == want)
        and any(
            isinstance(row, dict) and _agent_has_race_result(row)
            for row in stored.get("rows") or []
        )
    ):
        return True
    if race_id:
        try:
            table = store.load_race_table(race_id)
        except Exception:
            table = None
        if table and any(
            isinstance(row, dict) and _agent_has_race_result(row)
            for row in table.get("rows") or []
        ):
            return True
    return False


def _api_rankings_tallied(source: dict | None) -> bool:
    """True only when the public race payload has a winner or per-agent scores.

    A local backfill (race table or validator-run means) must not count. Treating
    that as official is what drops Overview onto the next qualifying board, where
    R is empty by design.
    """
    race = _live_race_payload(source)
    if race.get("winner_agent_name") or race.get("winner_score") is not None:
        return True
    return any(_agent_has_race_result(item) for item in _live_race_agents(source))


def _rankings_tallied(source: dict | None) -> bool:
    if _api_rankings_tallied(source):
        return True
    race = _live_race_payload(source)
    return _stored_rankings_tallied(
        str(race.get("race_id") or (source or {}).get("race_id") or ""),
        race.get("race_number") or (source or {}).get("race_number"),
    )


def _with_finished_race(payload: dict) -> dict:
    card = _finished_race_card()
    if card:
        payload["finished_race"] = card
    elif "finished_race" not in payload:
        payload["finished_race"] = None
    return payload


def _finished_race_card(item: dict | None = None) -> dict | None:
    source = item if isinstance(item, dict) else _latest_scored_history_item()
    if not isinstance(source, dict):
        return None
    race_id = str(source.get("race_id") or "")
    stored = store.load_race_summary(race_id) if race_id else None
    if stored:
        stored = _apply_stored_leaders(stored)
    else:
        stored = {}
    overall_agent = stored.get("overall_agent")
    race_agent = stored.get("race_agent")
    if not overall_agent or not race_agent:
        return None
    return {
        "race_number": stored.get("race_number") or source.get("race_number"),
        "status": "RACE_COMPLETE",
        "overall_agent": overall_agent,
        "overall_score": stored.get("overall_score"),
        "race_agent": race_agent,
        "race_score": stored.get("race_score"),
    }


def _stored_race_anchor(race_number: object) -> float | None:
    number = _race_num(race_number)
    if number is None:
        return None
    try:
        stored = store.load_race_thresholds()
    except Exception:
        stored = {}
    value = _as_float(stored.get(number))
    if value is not None:
        return value
    try:
        summaries = store.load_all_race_summaries()
    except Exception:
        summaries = {}
    for row in summaries.values():
        if not isinstance(row, dict) or _race_num(row.get("race_number")) != number:
            continue
        value = _as_float(row.get("race_threshold"))
        if value is not None:
            return value
    return None


def _overview_summary(stored: dict) -> dict:
    rows = [row for row in stored.values() if isinstance(row, dict)]
    latest = max(rows, key=lambda row: row.get("race_number") or 0)
    if _status_upper(latest.get("status")) in {"RACE_RUNNING", "RUNNING", "IN_PROGRESS"}:
        return latest
    scored = [
        row
        for row in rows
        if _status_upper(row.get("status")) in _RACE_SCORED_STATUS
    ]
    if scored:
        return max(scored, key=lambda row: row.get("race_number") or 0)
    return latest


def _latest_scored_mongo_item() -> dict | None:
    try:
        stored = store.load_all_race_summaries()
    except Exception:
        stored = {}
    scored = [
        row
        for row in stored.values()
        if isinstance(row, dict) and _status_upper(row.get("status")) in _RACE_SCORED_STATUS
    ]
    if not scored:
        return None
    return max(scored, key=lambda row: _race_num(row.get("race_number")) or 0)


def _latest_scored_history_item() -> dict | None:
    try:
        history = _fetch_json(f"{ORO_BASE}/races/history?limit=4", timeout=12, quick=True)
    except _FETCH_ERRORS:
        return _latest_scored_mongo_item()
    races = history.get("races") if isinstance(history, dict) else None
    if not isinstance(races, list):
        return _latest_scored_mongo_item()
    scored = [
        item
        for item in races
        if isinstance(item, dict) and _status_upper(item.get("status")) in _RACE_SCORED_STATUS
    ]
    if not scored:
        return _latest_scored_mongo_item()
    return max(scored, key=lambda item: _race_num(item.get("race_number")) or 0)


def _as_live_ranking_wrap(wrap: dict, race: dict) -> dict:
    return {**wrap, "race": {**race, "status": "LIVE_RANKING"}}


def _overview_race_wrap(current_wrap: dict, *, timeout: float, quick: bool) -> dict:
    race = (
        current_wrap.get("race")
        if isinstance(current_wrap.get("race"), dict)
        else current_wrap
    )
    if not isinstance(race, dict):
        return current_wrap
    status = _status_upper(race.get("status"))
    if status in {"RACE_RUNNING", "RUNNING", "IN_PROGRESS", "LIVE_RANKING"}:
        return current_wrap
    if status == "RACE_COMPLETE":
        if _api_rankings_tallied(current_wrap):
            return current_wrap
        return _as_live_ranking_wrap(current_wrap, race)
    if not _is_qualifying_only(status):
        return current_wrap
    item = _latest_scored_history_item()
    race_id = str((item or {}).get("race_id") or "")
    if not race_id:
        return current_wrap
    prev_n = _race_num((item or {}).get("race_number"))
    official_n = _race_num(race.get("race_number"))
    if official_n is not None and prev_n is not None and prev_n >= official_n:
        return current_wrap
    if _api_rankings_tallied(item):
        return current_wrap
    try:
        wrap = _fetch_json(f"{ORO_BASE}/races/{race_id}", timeout=timeout, quick=quick)
    except _FETCH_ERRORS:
        if item:
            return _as_live_ranking_wrap({"race": item}, item)
        return current_wrap
    live_race = wrap.get("race") if isinstance(wrap.get("race"), dict) else None
    if not isinstance(live_race, dict):
        return current_wrap
    if _api_rankings_tallied(wrap):
        return current_wrap
    return _as_live_ranking_wrap(wrap, live_race)


def _standings_from_mongo() -> dict | None:
    stored = store.load_all_race_summaries()
    if not stored:
        return None
    latest = _overview_summary(stored)
    table = store.load_race_table(str(latest.get("race_id") or ""))
    if not table or not table.get("rows"):
        return None
    rows = []
    for index, row in enumerate(table["rows"], start=1):
        history = [
            {"race_number": point.get("race_number"), "score": point.get("score")}
            for point in (row.get("races") or [])
            if point.get("score") is not None
            and point.get("race_number") != (table.get("race_number") or latest.get("race_number"))
        ]
        history = list(reversed(history[-2:]))
        while len(history) < 2:
            history.append({"race_number": None, "score": None})
        previous = [
            {
                "race_number": table.get("race_number") or latest.get("race_number"),
                "score": row.get("race_score"),
            },
            history[0],
            history[1],
        ]
        rows.append(
            {
                "rank": row.get("rank") if row.get("rank") is not None else index,
                "agent_name": row.get("agent_name") or "",
                "agent_version_id": row.get("agent_version_id") or "",
                "version_number": row.get("version_number"),
                "miner_hotkey": row.get("miner_hotkey") or "",
                "coldkey": row.get("coldkey") or "",
                "qualifying_score": row.get("qualifying_score"),
                "race_score": row.get("race_score"),
                "overall_score": row.get("overall_score"),
                "margin": None,
                "previous": previous,
            }
        )
    race_number = table.get("race_number") or latest.get("race_number")
    return {
        "race_number": race_number,
        "race_status": _overview_display_status(latest.get("status")),
        "race_threshold": _as_float(latest.get("race_threshold"))
        or _stored_race_anchor(race_number),
        "qualifying_threshold": _as_float(latest.get("qualifying_threshold")),
        "total": len(rows),
        "rows": rows,
        "updated_at": table.get("updated_at"),
    }


def _fallback_standings(race_number: object = None) -> dict | None:
    stored = store.load_current_standings()
    from_tables = _standings_from_mongo()
    candidates = [
        row
        for row in (stored, from_tables)
        if row and row.get("rows")
        and (race_number is None or row.get("race_number") == race_number)
    ]
    preferred = [
        row
        for row in candidates
        if not _is_qualifying_only(row.get("race_status") or row.get("status"))
    ]
    official_n = _race_num((_official_current_meta or {}).get("race_number"))
    if (
        official_n is not None
        and _is_qualifying_only((_official_current_meta or {}).get("status"))
        and not preferred
    ):
        match = [row for row in candidates if _race_num(row.get("race_number")) == official_n]
        if match:
            return match[0]
        if race_number is None:
            return None
    pick = preferred or candidates
    return pick[0] if pick else None


_live_scores: dict[str, dict[str, float]] = {}
_live_enrich_lock = threading.Lock()
_live_enriching: set[str] = set()
_last_in_progress: dict[str, set[str]] = {}
_LIVE_FETCH_LIMIT = 12


def _runs_list(runs: object) -> list:
    if isinstance(runs, list):
        return [item for item in runs if isinstance(item, dict)]
    if isinstance(runs, dict):
        for key in ("runs", "items", "results", "data"):
            value = runs.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _score_from_runs(runs: object, race_id: str, *, min_runs: int = 2) -> float | None:
    items = _runs_list(runs)
    if not race_id or not items:
        return None
    scores: list[float] = []
    fallback: list[float] = []
    for run in items:
        if not isinstance(run, dict):
            continue
        run_race = str(run.get("race_id") or "")
        if run_race and run_race != race_id:
            continue
        phase = str(run.get("phase") or "").upper()
        if phase and phase not in {"RACE", "RACING"}:
            continue
        status = str(run.get("status") or "").upper().replace(" ", "_")
        if status not in {"SUCCESS", "COMPLETED", "COMPLETE"}:
            continue
        if run.get("is_included") is False:
            continue
        score = _as_float(
            run.get("validator_score") if run.get("validator_score") is not None else run.get("score")
        )
        if score is None:
            continue
        if run_race == race_id:
            scores.append(score)
        else:
            fallback.append(score)
    picked = scores or fallback
    if len(picked) < min_runs:
        return None
    return round(sum(picked) / len(picked), 4)


def _load_live_scores(race_id: str) -> dict[str, float]:
    if not race_id:
        return {}
    stored = store.load_live_race_scores(race_id)
    with _live_enrich_lock:
        merged = {**(_live_scores.get(race_id) or {}), **stored}
        _live_scores[race_id] = merged
        return dict(merged)


def _eval_items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("evaluations") or payload.get("data") or []
        return [item for item in items if isinstance(item, dict)]
    return []


def _pending_items(*, quick: bool = False) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while offset <= 2000:
        try:
            payload = _fetch_any(
                f"{ORO_BASE}/evaluations/pending?limit=200&offset={offset}",
                timeout=8 if quick else 15,
                quick=quick,
            )
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            OSError,
            json.JSONDecodeError,
        ):
            break
        items = _eval_items(payload)
        rows.extend(items)
        if len(items) < 200:
            break
        offset += 200
    return rows


def _running_items(*, quick: bool = False) -> list[dict]:
    try:
        return _eval_items(
            _fetch_any(f"{ORO_BASE}/evaluations/running", timeout=8 if quick else 15, quick=quick)
        )
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        OSError,
        json.JSONDecodeError,
    ):
        return []


def _eval_done_need(item: dict) -> tuple[int, int]:
    completed = item.get("completed_successes")
    required = item.get("required_successes") or 2
    try:
        done = int(completed) if completed is not None else 0
        need = int(required)
    except (TypeError, ValueError):
        return 0, 2
    return done, need


def _eval_score(item: dict, race_id: str) -> float | None:
    item_race = str(item.get("race_id") or "")
    if race_id and item_race and item_race != race_id:
        return None
    for key in ("race_score", "validator_score", "score", "final_score"):
        value = _as_float(item.get(key))
        if value is not None:
            return value
    return None


def _is_race_eval(item: dict, race_id: str = "") -> bool:
    phase = str(item.get("phase") or "").upper()
    if phase and phase not in {"RACE", "RACING"}:
        return False
    item_race = str(item.get("race_id") or "")
    if race_id and item_race and item_race != race_id:
        return False
    return bool(phase or item_race or race_id)


def _version_progress(
    pending: list[dict] | None = None,
    running: list[dict] | None = None,
    race_id: str = "",
    *,
    quick: bool = False,
) -> tuple[set[str], set[str], list[dict]]:
    pending = _pending_items(quick=quick) if pending is None else pending
    running = _running_items(quick=quick) if running is None else running
    finished: set[str] = set()
    in_progress: set[str] = set()
    for item in pending:
        version_id = str(item.get("agent_version_id") or "")
        if not version_id or not _is_race_eval(item, race_id):
            continue
        done, need = _eval_done_need(item)
        if done >= need:
            finished.add(version_id)
        else:
            in_progress.add(version_id)
    for item in running:
        version_id = str(item.get("agent_version_id") or "")
        if version_id and version_id not in finished and _is_race_eval(item, race_id):
            in_progress.add(version_id)
    return finished, in_progress, pending


def _busy_version_ids() -> set[str]:
    _finished, in_progress, _pending = _version_progress()
    return in_progress


def _patch_standings_live_scores(found: dict[str, float]) -> None:
    global _standings_cache
    if not found:
        return
    with _standings_lock:
        if not _standings_cache:
            return
        payload = dict(_standings_cache[1])
        rows = [dict(row) for row in payload.get("rows") or []]
        changed = False
        for row in rows:
            version_id = str(row.get("agent_version_id") or "")
            score = found.get(version_id)
            if score is None or row.get("race_score") is not None:
                continue
            row["race_score"] = score
            previous = [dict(point) for point in (row.get("previous") or [])]
            if previous:
                previous[0]["score"] = score
                row["previous"] = previous
            changed = True
        if not changed:
            return
        scored = [row for row in rows if row.get("race_score") is not None]
        waiting = [row for row in rows if row.get("race_score") is None]
        scored.sort(key=lambda row: (-(row.get("race_score") or 0), str(row.get("agent_name") or "").lower()))
        waiting.sort(
            key=lambda row: (
                -(row.get("qualifying_score") or 0),
                str(row.get("agent_name") or "").lower(),
            )
        )
        ranked = scored + waiting
        for index, row in enumerate(ranked, start=1):
            row["rank"] = index
        payload["rows"] = ranked
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        _standings_cache = (time.monotonic(), payload)
    store.save_current_standings(payload)


def _fetch_live_scores_for(
    race_id: str,
    version_ids: list[str],
    *,
    quick: bool = False,
    min_runs: int = 2,
) -> dict[str, float]:
    need = [version_id for version_id in dict.fromkeys(version_ids) if version_id]
    if not race_id or not need:
        return {}

    def _one(version_id: str) -> tuple[str, float | None]:
        try:
            runs = _fetch_any(
                f"{ORO_BASE}/agent-versions/{version_id}/runs",
                timeout=8 if quick else 20,
                quick=quick,
            )
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            OSError,
            json.JSONDecodeError,
        ):
            return version_id, None
        return version_id, _score_from_runs(runs, race_id, min_runs=min_runs)

    found: dict[str, float] = {}
    workers = min(10 if not quick else 6, len(need))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for version_id, score in pool.map(_one, need):
            if score is not None:
                found[version_id] = score
    if not found:
        return {}
    store.save_live_race_scores(race_id, found)
    with _live_enrich_lock:
        _live_scores.setdefault(race_id, {}).update(found)
    return found


def _collect_new_live_scores(
    race_id: str,
    version_ids: list[str],
    *,
    force: bool = False,
    known: dict[str, float] | None = None,
    quick: bool = False,
    fetch_all: bool = False,
    min_runs: int = 2,
) -> dict[str, float]:
    have = {} if force else _load_live_scores(race_id)
    if known:
        have = {**have, **{key: value for key, value in known.items() if value is not None}}
    finished, in_progress, pending = _version_progress(race_id=race_id, quick=quick)
    found: dict[str, float] = {}
    for item in pending:
        version_id = str(item.get("agent_version_id") or "")
        if not version_id or version_id in have or version_id in found:
            continue
        if not _is_race_eval(item, race_id):
            continue
        done, need = _eval_done_need(item)
        if done < need:
            continue
        score = _eval_score(item, race_id)
        if score is not None:
            found[version_id] = score
    prev = _last_in_progress.get(race_id) or set()
    _last_in_progress[race_id] = in_progress
    need = [
        version_id
        for version_id in dict.fromkeys(
            [
                *finished,
                *(prev - in_progress),
                *[
                    item
                    for item in version_ids
                    if item and item not in have and item not in in_progress
                ],
            ]
        )
        if version_id and version_id not in have and version_id not in found
    ]
    if not force and not fetch_all:
        need = need[:_LIVE_FETCH_LIMIT]
    found.update(_fetch_live_scores_for(race_id, need, quick=quick, min_runs=min_runs))
    if found:
        have.update(found)
        store.save_live_race_scores(race_id, found)
        with _live_enrich_lock:
            _live_scores.setdefault(race_id, {}).update(found)
    return have


def _refresh_live_scores(
    race_id: str,
    version_ids: list[str],
    *,
    force: bool = False,
    known: dict[str, float] | None = None,
    quick: bool = False,
    fetch_all: bool = False,
    min_runs: int = 2,
) -> dict[str, float]:
    return _collect_new_live_scores(
        race_id,
        version_ids,
        force=force,
        known=known,
        quick=quick,
        fetch_all=fetch_all,
        min_runs=min_runs,
    )


def _enrich_live_scores(race_id: str, version_ids: list[str]) -> None:
    try:
        before = set(_load_live_scores(race_id))
        have = _collect_new_live_scores(race_id, version_ids)
        found = {key: value for key, value in have.items() if key not in before}
        if found:
            _patch_standings_live_scores(found)
    finally:
        with _live_enrich_lock:
            _live_enriching.discard(race_id)


def _start_live_score_enrich(race_id: str, version_ids: list[str]) -> None:
    if not race_id or not version_ids:
        return
    with _live_enrich_lock:
        if race_id in _live_enriching:
            return
        _live_enriching.add(race_id)
    threading.Thread(
        target=_enrich_live_scores,
        args=(race_id, version_ids),
        daemon=True,
    ).start()


def _last_good_standings() -> dict | None:
    with _standings_lock:
        if _standings_cache and (_standings_cache[1].get("rows") or []):
            return _standings_cache[1]
    return _fallback_standings()


def _window_from_row(row: dict) -> list[dict]:
    window = row.get("window")
    if isinstance(window, list) and window:
        return [entry for entry in window if isinstance(entry, dict)]
    points = row.get("races")
    if isinstance(points, list) and points:
        return _score_window(row)
    prior_points = row.get("previous")
    rebuilt: list[dict] = []
    if isinstance(prior_points, list):
        for point in prior_points:
            if not isinstance(point, dict):
                continue
            number = _race_num(point.get("race_number"))
            raw = _as_float(point.get("score") if point.get("score") is not None else point.get("raw_score"))
            if number is None or raw is None:
                continue
            rebuilt.append({"race_number": number, "raw_score": raw})
    for part in row.get("margins") or []:
        if not isinstance(part, dict):
            continue
        number = _race_num(part.get("race_number"))
        delta = _as_float(part.get("score"))
        if number is None or delta is None:
            continue
        entry = next((item for item in rebuilt if item.get("race_number") == number), None)
        if entry is None:
            entry = {"race_number": number}
            rebuilt.append(entry)
        if entry.get("delta") is None and _window_raw(entry) is None:
            entry["delta"] = delta / 100.0
    return rebuilt


def _official_field_anchors(
    current_number: object = None,
    current_id: str = "",
    *,
    force: bool = False,
) -> dict[int, float]:
    current = _race_num(current_number)
    with _prev_windows_lock:
        cached = _prev_windows_cache
        memory = (
            dict(cached.get("anchors") or {})
            if cached and cached.get("for_current") == current and cached.get("anchors")
            else {}
        )
    try:
        stored = store.load_race_thresholds()
    except Exception:
        stored = {}
    if memory:
        stored = {**stored, **memory}
    need_prev = current is not None and (
        force
        or not memory
        or any(number not in stored for number in _latest_finished_prior_numbers(current, current_id))
    )
    if need_prev:
        _load_previous_windows(current_number, current_id, force=force)
        with _prev_windows_lock:
            cached = _prev_windows_cache
            if cached and cached.get("for_current") == current and cached.get("anchors"):
                stored = {**stored, **dict(cached.get("anchors") or {})}
        try:
            stored = {**stored, **store.load_race_thresholds()}
        except Exception:
            pass
    return stored


def _prior_race_coverage(index: dict, race_number: int | None) -> int:
    """How many WIN identities carry a raw score for race_number."""
    number = _race_num(race_number)
    if number is None or not index:
        return 0
    hits = 0
    for window in index.values():
        if not isinstance(window, list):
            continue
        if any(
            _race_num(entry.get("race_number")) == number and _window_raw(entry) is not None
            for entry in window
            if isinstance(entry, dict)
        ):
            hits += 1
    return hits


def _index_previous_row_windows(
    rows: list[dict],
    number: int | None,
    field: float | None,
    by_version: dict[str, list[dict]],
    by_name_version_hotkey: dict[str, list[dict]],
) -> None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        version_id = str(row.get("agent_version_id") or "")
        nvh_key = _name_version_hotkey_key(
            row.get("agent_name"), row.get("version_number"), row.get("miner_hotkey")
        )
        window = _window_from_row(row)
        official = next(
            (
                item
                for item in window
                if _race_num(item.get("race_number")) == number
            ),
            {},
        )
        if official.get("is_seed"):
            # Seed placeholders are not real finishes for this version — skip.
            continue
        raw = _qualifier_race_score(row, number)
        if raw is None:
            raw = _as_float(official.get("raw_score"))
        if number is None or raw is None:
            continue
        entry: dict = {"race_number": number, "raw_score": raw, "anchor": field}
        # Prefer ORO window.anchor / window.delta for this race_id point.
        if official.get("anchor") is not None:
            entry["anchor"] = _as_float(official.get("anchor"))
        elif field is not None:
            entry["anchor"] = field
        if official.get("delta") is not None:
            entry["delta"] = _as_float(official.get("delta"))
            entry["oro_delta"] = True
        elif entry.get("anchor") is not None:
            entry["delta"] = raw - entry["anchor"]
        point = [entry]
        if version_id:
            by_version[version_id] = _merge_window(point, by_version.get(version_id) or [])
        if nvh_key:
            by_name_version_hotkey[nvh_key] = _merge_window(
                point, by_name_version_hotkey.get(nvh_key) or []
            )


def _official_field_for_race_id(
    race_id: str,
    number: int | None,
    rows: list[dict] | None = None,
    *,
    quick: bool = True,
) -> float | None:
    """Official ORO window anchor for a finished race_id (not a polluted race_number top-half)."""
    global _prev_windows_cache
    race_id = str(race_id or "")
    if not race_id:
        return _top_half_anchor(rows or [], number)
    with _prev_windows_lock:
        cached = _prev_windows_cache or {}
        by_id = cached.get("anchors_by_id") or {}
        if race_id in by_id and by_id.get(race_id) is not None:
            return _as_float(by_id.get(race_id))
    race: dict = {"race_id": race_id, "race_number": number}
    quals: list[dict] = []
    try:
        wrap = _fetch_json(
            f"{ORO_BASE}/races/{race_id}",
            timeout=8 if quick else 25,
            quick=quick,
        )
        if isinstance(wrap.get("race"), dict):
            race = {**race, **wrap["race"]}
        quals = [row for row in (wrap.get("qualifiers") or []) if isinstance(row, dict)]
    except Exception:
        quals = []
    field = _race_anchor(race, quals) if quals else None
    if field is None:
        field = _as_float(race.get("challenge_threshold") or race.get("anchor"))
    if field is None:
        field = _top_half_anchor(rows or quals, number)
    if field is not None:
        with _prev_windows_lock:
            cached = dict(_prev_windows_cache or {})
            by_id = dict(cached.get("anchors_by_id") or {})
            by_id[race_id] = field
            cached["anchors_by_id"] = by_id
            if number is not None:
                anchors = dict(cached.get("anchors") or {})
                anchors[number] = field
                cached["anchors"] = anchors
            _prev_windows_cache = cached
        try:
            if number is not None:
                store.save_race_thresholds({number: field})
            store.save_race_summary(
                {
                    "race_id": race_id,
                    "race_number": number,
                    "race_threshold": field,
                    "status": race.get("status"),
                }
            )
        except Exception:
            pass
    return field


def _backfill_previous_from_local_tables(
    current: int | None,
    anchors: dict[int, float],
    by_version: dict[str, list[dict]],
    by_name_version_hotkey: dict[str, list[dict]],
    *,
    prior_numbers: list[int] | None = None,
    current_id: str = "",
) -> None:
    """Fill WIN gaps from the two latest finished race tables."""
    del current  # priors are chronological across suite resets
    meta = _latest_finished_prior_meta(current_id, limit=2)
    if prior_numbers:
        wanted_meta = []
        by_num_meta = {item["race_number"]: item for item in meta}
        for number in prior_numbers:
            item = by_num_meta.get(number)
            if item:
                wanted_meta.append(item)
            else:
                wanted_meta.append({"race_number": number, "race_id": ""})
        meta = wanted_meta
    if not meta:
        return
    for item in meta:
        number = _race_num(item.get("race_number"))
        race_id = str(item.get("race_id") or "")
        if number is None:
            continue
        table = None
        if race_id:
            try:
                table = store.load_race_table(race_id)
            except Exception:
                table = None
        if not isinstance(table, dict) or not (table.get("rows") or []):
            try:
                tables = store.load_race_tables_by_numbers([number])
            except Exception:
                tables = {}
            table = tables.get(number) if isinstance(tables, dict) else None
            if isinstance(table, dict) and not race_id:
                race_id = str(table.get("race_id") or "")
        if not isinstance(table, dict):
            continue
        rows = [row for row in (table.get("rows") or []) if isinstance(row, dict)]
        if not rows:
            continue
        # Prefer live ORO qualifier windows (official anchor/delta) when available.
        oro_rows: list[dict] = []
        if race_id:
            try:
                wrap = _fetch_json(f"{ORO_BASE}/races/{race_id}", timeout=12, quick=True)
                quals = [row for row in (wrap.get("qualifiers") or []) if isinstance(row, dict)]
                if quals:
                    oro_rows = quals
                    race = wrap.get("race") if isinstance(wrap.get("race"), dict) else {}
                    field = _race_anchor(race, quals) if race else None
                    if field is None:
                        field = _as_float((race or {}).get("challenge_threshold"))
                    if field is not None:
                        anchors[number] = field
                        try:
                            store.save_race_thresholds({number: field})
                        except Exception:
                            pass
            except Exception:
                oro_rows = []
        # Official window.anchor from ORO for this race_id — never reuse a
        # race_number top-half left over from an older suite.
        field = anchors.get(number)
        if field is None:
            field = _official_field_for_race_id(race_id, number, rows, quick=True)
        if field is None:
            field = _top_half_anchor(oro_rows or rows, number)
        if field is not None:
            anchors[number] = field
        _index_previous_row_windows(
            oro_rows or rows, number, field, by_version, by_name_version_hotkey
        )
        # Local table only fills agents ORO omitted — never overwrite official deltas.
        if oro_rows and rows:
            have_vid = set(by_version)
            have_nvh = set(by_name_version_hotkey)
            extras = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                vid = str(row.get("agent_version_id") or "")
                nvh = _name_version_hotkey_key(
                    row.get("agent_name"), row.get("version_number"), row.get("miner_hotkey")
                )
                if (vid and vid in have_vid) or (nvh and nvh in have_nvh):
                    continue
                extras.append(row)
            if extras:
                _index_previous_row_windows(
                    extras, number, field, by_version, by_name_version_hotkey
                )


def _load_previous_windows(
    current_number: object,
    current_id: str,
    *,
    force: bool = False,
) -> dict[str, list[dict]]:
    global _prev_windows_cache
    current = _race_num(current_number)
    priors = _latest_finished_prior_numbers(current, current_id)
    if not force:
        with _prev_windows_lock:
            cached = _prev_windows_cache
            if (
                cached
                and cached.get("for_current") == current
                and list(cached.get("prior_numbers") or []) == priors
                and cached.get("by_version") is not None
                and cached.get("by_name_version_hotkey") is not None
                and cached.get("anchors") is not None
                and (
                    not priors
                    or all(
                        _prior_race_coverage(cached.get("by_name_version_hotkey") or {}, number) > 0
                        or _prior_race_coverage(cached.get("by_version") or {}, number) > 0
                        for number in priors
                    )
                )
            ):
                return cached["by_version"]
    by_version: dict[str, list[dict]] = {}
    by_name_version_hotkey: dict[str, list[dict]] = {}
    anchors: dict[int, float] = {}
    prior_meta: list[dict] = []
    try:
        anchors.update(store.load_race_thresholds())
    except Exception:
        pass
    # Local tables first so Overview WIN/Margin stay correct even when live
    # history fetches time out during QUALIFYING_OPEN.
    _backfill_previous_from_local_tables(
        current,
        anchors,
        by_version,
        by_name_version_hotkey,
        prior_numbers=priors,
        current_id=current_id,
    )
    try:
        history = _fetch_json(f"{ORO_BASE}/races/history?limit=8", timeout=20, quick=False)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError, urllib.error.HTTPError):
        history = {}
    races = history.get("races") if isinstance(history, dict) else None
    need = []
    seen_ids: set[str] = set()
    suite = _resolve_current_suite_id(current_id)
    if isinstance(races, list):
        for hist in races:
            if not isinstance(hist, dict):
                continue
            race_id = str(hist.get("race_id") or "")
            if not race_id or race_id == current_id or race_id in seen_ids:
                continue
            number = _race_num(hist.get("race_number"))
            if number is None:
                continue
            row_suite = _suite_int(hist.get("suite_id"))
            if suite is None and row_suite is not None:
                suite = row_suite
            if suite is not None and row_suite is not None and row_suite != suite:
                continue
            seen_ids.add(race_id)
            need.append(hist)
            prior_meta.append({"race_number": number, "race_id": race_id, "suite_id": row_suite})
            if len(need) >= 2:
                break

    def _rows_for(hist: dict) -> tuple[dict, list[dict], dict]:
        race_id = str(hist.get("race_id") or "")
        try:
            wrap = _fetch_json(f"{ORO_BASE}/races/{race_id}", timeout=25, quick=False)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError, urllib.error.HTTPError):
            wrap = {}
        race = wrap.get("race") if isinstance(wrap.get("race"), dict) else hist
        qualifiers = wrap.get("qualifiers")
        if isinstance(qualifiers, list) and qualifiers:
            return hist, [row for row in qualifiers if isinstance(row, dict)], race if isinstance(race, dict) else hist
        stored = store.load_race_table(race_id) if race_id else None
        rows = [row for row in (stored or {}).get("rows") or [] if isinstance(row, dict)]
        return hist, rows, race if isinstance(race, dict) else hist

    lists: list[tuple[dict, list[dict], dict]] = []
    if need:
        with ThreadPoolExecutor(max_workers=len(need)) as pool:
            lists = list(pool.map(_rows_for, need))
    for hist, rows, race in lists:
        number = _race_num(hist.get("race_number") or race.get("race_number"))
        field = (
            _as_float(race.get("challenge_threshold"))
            or _race_anchor(race, rows)
            or _top_half_anchor(rows, number)
        )
        if number is not None and field is None:
            field = _stored_race_anchor(number)
        if number is not None and field is not None:
            anchors[number] = field
            try:
                store.save_race_summary(
                    {
                        "race_id": str(hist.get("race_id") or race.get("race_id") or ""),
                        "race_number": number,
                        "status": hist.get("status") or race.get("status"),
                        "race_threshold": field,
                    }
                )
            except Exception:
                pass
        _index_previous_row_windows(rows, number, field, by_version, by_name_version_hotkey)
    if prior_meta:
        priors = [int(item["race_number"]) for item in prior_meta if item.get("race_number") is not None]
    else:
        prior_meta = _latest_finished_prior_meta(current_id, limit=2)
        priors = [int(item["race_number"]) for item in prior_meta if item.get("race_number") is not None]
    # Merge again after live fetch in case local tables were thinner.
    _backfill_previous_from_local_tables(
        current,
        anchors,
        by_version,
        by_name_version_hotkey,
        prior_numbers=priors,
        current_id=current_id,
    )
    if anchors:
        try:
            store.save_race_thresholds(anchors)
        except Exception:
            pass
    if by_version or by_name_version_hotkey or anchors or priors:
        with _prev_windows_lock:
            prev = _prev_windows_cache or {}
            _prev_windows_cache = {
                "for_current": current,
                "by_version": by_version,
                "by_name_version_hotkey": by_name_version_hotkey,
                "anchors": anchors,
                "prior_numbers": priors,
                "prior_meta": prior_meta,
                "anchors_by_id": dict(prev.get("anchors_by_id") or {}),
            }
    return by_version


def _start_standings_refresh() -> None:
    global _standings_refreshing
    with _standings_lock:
        if _standings_refreshing:
            return
        _standings_refreshing = True

    def _run() -> None:
        global _standings_refreshing
        try:
            _build_current_standings(refresh=False, quick=True)
        except Exception:
            pass
        finally:
            with _standings_lock:
                _standings_refreshing = False

    threading.Thread(target=_run, daemon=True).start()


_OVERVIEW_POLL_SECONDS = 30
_overview_poller_started = False
_overview_poller_lock = threading.Lock()


def _overview_poll_loop() -> None:
    while True:
        started = time.monotonic()
        try:
            _build_current_standings(refresh=False, quick=True, poll=True)
        except Exception:
            pass
        delay = _OVERVIEW_POLL_SECONDS - (time.monotonic() - started)
        time.sleep(max(0.5, delay))


def start_overview_poller() -> None:
    global _overview_poller_started
    with _overview_poller_lock:
        if _overview_poller_started:
            return
        _overview_poller_started = True
    threading.Thread(
        target=_overview_poll_loop,
        daemon=True,
        name="overview-oro-poll",
    ).start()


def _apply_race_margins(payload: dict) -> dict:
    if _is_qualifying_only(payload.get("race_status") or payload.get("status")):
        return payload
    threshold = _as_float(payload.get("race_threshold"))
    rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
    for row in rows:
        row["race_margin"] = _race_anchor_margin(row.get("race_score"), threshold)
    payload["rows"] = rows
    return payload


def _preserve_richer_previous(payload: dict, prior_rows: list) -> dict:
    """Keep finished-race WIN scores when a rebuild briefly fails to look them up.

    Only restores scores that the current version_id / name+version+hotkey index
    still owns — never reapply another hotkey's WIN onto this row.
    """
    if not prior_rows or not isinstance(payload.get("rows"), list):
        return payload
    with _prev_windows_lock:
        cached = _prev_windows_cache or {}
    nvh_index = cached.get("by_name_version_hotkey") or {}
    vid_index = cached.get("by_version") or {}
    by_nvh: dict[str, dict] = {}
    by_vid: dict[str, dict] = {}
    for row in prior_rows:
        if not isinstance(row, dict):
            continue
        nvh = _name_version_hotkey_key(
            row.get("agent_name"), row.get("version_number"), row.get("miner_hotkey")
        )
        vid = str(row.get("agent_version_id") or "")
        if nvh:
            by_nvh[nvh] = row
        if vid:
            by_vid[vid] = row
    if not by_nvh and not by_vid:
        return payload

    def _allowed_scores(nvh: str, vid: str) -> dict[int, float]:
        allowed: dict[int, float] = {}
        for entry in (*(vid_index.get(vid) or []), *(nvh_index.get(nvh) or [])):
            if not isinstance(entry, dict):
                continue
            number = _race_num(entry.get("race_number"))
            raw = _window_raw(entry)
            if number is not None and raw is not None:
                allowed[number] = raw
        return allowed

    rows: list[dict] = []
    for row in payload["rows"]:
        if not isinstance(row, dict):
            continue
        out = dict(row)
        prev = [dict(point) for point in (out.get("previous") or []) if isinstance(point, dict)]
        if not prev:
            rows.append(out)
            continue
        nvh = _name_version_hotkey_key(
            out.get("agent_name"), out.get("version_number"), out.get("miner_hotkey")
        )
        vid = str(out.get("agent_version_id") or "")
        allowed = _allowed_scores(nvh, vid)
        if not allowed:
            rows.append(out)
            continue
        old = (by_vid.get(vid) if vid else None) or (by_nvh.get(nvh) if nvh else None)
        old_prev = (old or {}).get("previous") if isinstance(old, dict) else None
        if not isinstance(old_prev, list):
            rows.append(out)
            continue
        old_by = {
            _race_num(point.get("race_number")): _as_float(point.get("score"))
            for point in old_prev
            if isinstance(point, dict)
        }
        changed = False
        for point in prev:
            number = _race_num(point.get("race_number"))
            if number is None or point.get("score") is not None:
                continue
            if number not in allowed:
                continue
            kept = old_by.get(number)
            if kept is None:
                continue
            point["score"] = kept
            changed = True
        if changed:
            out["previous"] = prev
        rows.append(out)
    return {**payload, "rows": rows}


def _as_overview_payload(payload: dict) -> dict:
    payload = _heal_overview_identity(payload)
    # WIN/Margin warm must run before overall so prior race scores are indexed.
    return _with_finished_race(
        _fill_standings_overall(_with_key_fields(_apply_race_margins(payload)))
    )


def _pending_live_ranking(payload: dict | None) -> dict | None:
    if not payload or not payload.get("rows"):
        return None
    status = payload.get("race_status") or payload.get("status")
    if _is_qualifying_only(status):
        return None
    if _status_upper(status) in {"RACE_COMPLETE", "COMPLETED", "FINISHED", "CLOSED"}:
        return {**payload, "race_status": "LIVE_RANKING"}
    return payload


def get_current_race_standings(*, refresh: bool = False) -> dict:
    # Overview always prefers Mongo. The background poller refreshes that copy;
    # UI refresh must not force a live ORO rebuild (refresh arg ignored).
    del refresh
    start_overview_poller()
    stored = store.load_current_standings() or {}
    if stored.get("rows"):
        return _as_overview_payload(stored)
    try:
        return _build_current_standings(refresh=False, quick=True, poll=False)
    except Exception:
        pass
    fallback = _pending_live_ranking(_fallback_standings())
    if fallback:
        return _as_overview_payload(fallback)
    return _empty_standings()


def _build_current_standings(*, refresh: bool = False, quick: bool = False, poll: bool = False) -> dict:
    global _standings_cache
    fetch_timeout = 12 if poll else (20 if refresh else (8 if quick else 12))
    leave_live = False
    try:
        previous = store.load_current_standings() or {}
        leave_live = _status_upper(previous.get("race_status")) == "LIVE_RANKING" and (
            _stored_rankings_tallied("", previous.get("race_number"))
        )
    except Exception:
        leave_live = False
    official_wrap = _fetch_json(
        f"{ORO_BASE}/races/current",
        timeout=20 if (leave_live and poll) or refresh else fetch_timeout,
        quick=False if (leave_live and poll) or refresh else bool(quick or poll),
    )
    official_race = (
        official_wrap.get("race")
        if isinstance(official_wrap.get("race"), dict)
        else official_wrap
    )
    _set_official_current_meta(official_race if isinstance(official_race, dict) else None)
    current_wrap = _overview_race_wrap(
        official_wrap,
        timeout=20 if poll or refresh else fetch_timeout,
        quick=False if poll or refresh else bool(quick),
    )
    current_race = (
        current_wrap.get("race")
        if isinstance(current_wrap.get("race"), dict)
        else current_wrap
    )
    current_number = current_race.get("race_number")
    current_status = current_race.get("status")
    official_n = _race_num((official_race or {}).get("race_number"))
    current_n = _race_num(current_number)
    if (
        _is_qualifying_only((official_race or {}).get("status"))
        and official_n is not None
        and current_n is not None
        and official_n != current_n
    ):
        if _api_rankings_tallied(current_wrap):
            current_wrap = official_wrap
            current_race = official_race if isinstance(official_race, dict) else current_race
            current_number = current_race.get("race_number")
            current_status = current_race.get("status")
        else:
            kept = _fallback_standings(current_number)
            kept_rows = (kept or {}).get("rows") or []
            # Only reuse the stored table when it already has race scores.
            # A finished race often stores qualifiers with race_score still null;
            # returning that copy is what left Overview R empty.
            if kept_rows and any(
                isinstance(row, dict) and row.get("race_score") is not None for row in kept_rows
            ):
                payload = {
                    **kept,
                    "race_number": current_number,
                    "race_status": "LIVE_RANKING",
                    "race_threshold": _as_float(kept.get("race_threshold"))
                    or _stored_race_anchor(current_number),
                }
                payload = _as_overview_payload(payload)
                with _standings_lock:
                    _standings_cache = (time.monotonic(), payload)
                try:
                    store.save_current_standings(payload)
                except Exception:
                    pass
                return payload
    now_mono = time.monotonic()
    with _standings_lock:
        if (
            not refresh
            and not poll
            and _standings_cache
            and now_mono - _standings_cache[0] < CACHE_SECONDS
            and _standings_cache[1].get("race_number") == current_number
        ):
            return _standings_cache[1]
        prior_rows = (_standings_cache[1].get("rows") if _standings_cache else None) or []
    qualifiers = _current_race_agents(current_wrap.get("qualifiers"))
    if not current_number or not qualifiers:
        last = _last_good_standings()
        if _status_upper(current_status) == "LIVE_RANKING":
            kept = _fallback_standings(current_number)
            if kept and kept.get("rows"):
                payload = _as_overview_payload(
                    {
                        **kept,
                        "race_number": current_number,
                        "race_status": "LIVE_RANKING",
                    }
                )
                try:
                    store.save_current_standings(payload)
                except Exception:
                    pass
                return payload
            if last and _race_num(last.get("race_number")) == _race_num(current_number):
                return last
        if poll:
            return last or _empty_standings()
        if last:
            return last
    current_id = str(current_race.get("race_id") or "")
    previous_windows = _load_previous_windows(
        current_number, current_id, force=refresh and not poll
    )
    version_ids = [str(item.get("agent_version_id") or "") for item in qualifiers]
    known_scores = {
        str(item.get("agent_version_id") or ""): score
        for item in qualifiers
        if item.get("agent_version_id")
        and (score := _as_float(item.get("race_score"))) is not None
    }
    # A finished race can publish RACE_COMPLETE with every qualifier race_score
    # still null. The numbers are on each version's race runs; load them here
    # or Overview R stays blank after the site moves on.
    closed = _status_upper(current_status) in {
        "RACE_COMPLETE",
        "LIVE_RANKING",
        "COMPLETED",
        "FINISHED",
        "CLOSED",
    }
    needs_run_scores = bool(current_id) and closed and len(known_scores) < len(qualifiers)
    if current_id and (refresh or poll or needs_run_scores):
        live_scores = _refresh_live_scores(
            current_id,
            version_ids,
            force=refresh and not poll,
            known=known_scores,
            quick=bool(quick or poll) and not needs_run_scores,
            fetch_all=needs_run_scores,
            min_runs=1 if needs_run_scores else 2,
        )
    else:
        live_scores = {**known_scores, **_load_live_scores(current_id)}
    cold_by_hot: dict[str, str] = {}
    if not refresh or poll:
        try:
            cold_by_hot.update(store.load_hotkey_owners())
        except Exception:
            pass
        try:
            stored = store.load_current_standings() or {}
            extra_rows = stored.get("rows") or []
        except Exception:
            extra_rows = []
        for row in (*prior_rows, *extra_rows):
            if not isinstance(row, dict):
                continue
            hot = str(row.get("miner_hotkey") or "")
            cold = str(row.get("coldkey") or "")
            if hot and cold:
                cold_by_hot[hot] = cold
        try:
            for item in store.load_my_hotkeys().values():
                hotkey = str(item.get("ss58") or "")
                coldkey = str(item.get("coldkey") or "")
                if hotkey and coldkey:
                    cold_by_hot[hotkey] = coldkey
        except Exception:
            pass
    for item in qualifiers:
        hot = str(item.get("miner_hotkey") or "")
        cold = _item_coldkey(item)
        if hot and cold:
            cold_by_hot[hot] = cold
    try:
        uids = get_registered_uids(refresh=refresh and not poll)
        for item in uids.get("rows") or []:
            if not isinstance(item, dict):
                continue
            hot = str(item.get("hotkey") or "")
            cold = str(item.get("coldkey") or "")
            if hot and cold:
                cold_by_hot[hot] = cold
    except Exception:
        pass
    if cold_by_hot:
        try:
            store.save_hotkey_owners(cold_by_hot)
        except Exception:
            pass

    def _score_source(item: dict) -> dict:
        merged = {**item}
        # Ignore ORO embedded windows for prior races — they mix older versions
        # from the same hotkey. WIN only uses version_id / name+version+hotkey.
        current_pts = [
            entry
            for entry in _window_list(item)
            if _race_num(entry.get("race_number")) == _race_num(current_number)
        ]
        merged["window"] = _merge_window(current_pts, _lookup_previous_windows(item))
        return merged

    ranked = sorted(
        qualifiers,
        key=lambda item: (
            0 if _item_current_race_rank(item, current_status) is not None else 1,
            _item_current_race_rank(item, current_status) or 0,
            0
            if _item_race_score(
                item,
                current_number,
                current_status,
                live_scores.get(str(item.get("agent_version_id") or "")),
            )
            is not None
            else 1,
            -(
                _item_race_score(
                    item,
                    current_number,
                    current_status,
                    live_scores.get(str(item.get("agent_version_id") or "")),
                )
                or 0
            ),
            -(_as_float(item.get("qualifying_score")) or 0),
            str(item.get("agent_name") or "").lower(),
        ),
    )
    sources = [_score_source(item) for item in ranked]
    anchors = _official_field_anchors(current_number, current_id, force=refresh and not poll)
    if not anchors:
        anchors = _anchors_from_windows(sources)
    current_n = _race_num(current_number)
    current_anchor = _as_float(current_race.get("challenge_threshold")) or _race_anchor(
        current_race, qualifiers
    )
    if current_n is not None and current_anchor is not None:
        anchors[current_n] = current_anchor
    rows = []
    for index, (item, source) in enumerate(zip(ranked, sources), start=1):
        hotkey = str(item.get("miner_hotkey") or "")
        version_id = str(item.get("agent_version_id") or "")
        qualifying = _as_float(item.get("qualifying_score"))
        race_score = _item_race_score(
            item, current_number, current_status, live_scores.get(version_id)
        )
        race_rank = _item_current_race_rank(item, current_status)
        overall = (
            _current_overall_score(item, source, current_number)
            if _overall_ready(current_status)
            else None
        )
        race_margin = _current_race_margin(
            {**source, "race_score": race_score}, current_number, anchors
        ) or _race_anchor_margin(race_score, current_anchor)
        rows.append(
            {
                "rank": race_rank if race_rank is not None else index,
                "agent_name": item.get("agent_name") or "",
                "agent_version_id": version_id,
                "version_number": item.get("version_number"),
                "miner_hotkey": hotkey,
                "coldkey": _item_coldkey(item) or cold_by_hot.get(hotkey, ""),
                "qualifying_score": qualifying,
                "race_score": race_score,
                "overall_score": overall,
                "race_margin": race_margin,
                "margin": _margin_sum(source, current_number, anchors),
                "margins": _margin_parts(source, current_number, anchors),
                "previous": _previous_scores(
                    source,
                    current_number,
                    None if _is_qualifying_only(current_status) else race_score,
                ),
            }
        )
    payload = {
        **_empty_standings(),
        "race_number": current_number,
        "race_id": current_id,
        "suite_id": _suite_int(current_race.get("suite_id")),
        "race_status": current_status,
        "race_threshold": (
            _current_race_field_anchor(current_race, qualifiers, live_scores)
            if str(current_status or "").upper() in _RACE_SCORED_STATUS
            else next(
                (
                    value
                    for value in (
                        _race_anchor(current_race, qualifiers),
                        _as_float(current_race.get("anchor")),
                        _as_float(current_race.get("challenge_threshold")),
                    )
                    if value is not None
                ),
                None,
            )
        ),
        "qualifying_threshold": _as_float(current_race.get("qualifying_threshold")),
        "finished_race": _finished_race_card(),
        "total": len(rows),
        "rows": rows,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    payload = _as_overview_payload(payload)
    if poll and not rows:
        return _last_good_standings() or payload
    try:
        prior_stored = store.load_current_standings() or {}
        prior_for_preserve = list(prior_stored.get("rows") or []) if isinstance(prior_stored, dict) else []
    except Exception:
        prior_for_preserve = []
    if not prior_for_preserve:
        prior_for_preserve = list(prior_rows or [])
    payload = _preserve_richer_previous(payload, prior_for_preserve)
    current_n = _race_num(current_number)
    field = _as_float(payload.get("race_threshold"))
    if current_n is not None and field is not None:
        try:
            store.save_race_thresholds({current_n: field})
        except Exception:
            pass
    with _standings_lock:
        _standings_cache = (time.monotonic(), payload)
    try:
        store.save_current_standings(payload)
    except Exception:
        pass
    return payload


_races_lock = threading.Lock()
_races_cache: tuple[float, dict] | None = None
_race_summaries: dict[str, dict] = {}
_enrich_running = False


def _agent_label(item: dict) -> str | None:
    name = str(item.get("agent_name") or "").replace(" ", "_")
    if not name:
        return None
    version = item.get("version_number")
    if version is None or version == "":
        return name
    return f"{name}_v{version}"


def _top_by(qualifiers: list[dict], key: str) -> tuple[str | None, float | None]:
    best_item = None
    best_score = None
    for item in qualifiers:
        if item.get("is_discarded"):
            continue
        score = _as_float(item.get(key))
        if score is None:
            continue
        if best_score is None or score > best_score:
            best_score = score
            best_item = item
    if best_item is None:
        return None, None
    return _agent_label(best_item), best_score


def _race_top(qualifiers: list[dict], race: dict) -> tuple[str | None, float | None]:
    """Race-card leader: highest race_score (not ORO winner_agent / race_rank)."""
    number = _race_num(race.get("race_number"))
    best_item = None
    best_score = None
    for item in qualifiers:
        if not isinstance(item, dict) or item.get("is_discarded"):
            continue
        score = _qualifier_race_score(item, number)
        if score is None:
            continue
        if best_score is None or score > best_score:
            best_score = score
            best_item = item
    if best_item is not None:
        return _agent_label(best_item), best_score
    # Fallbacks when scores are not on qualifiers yet.
    winner_version = str(race.get("winner_agent_version_id") or "").strip()
    if winner_version:
        for item in qualifiers:
            if not isinstance(item, dict) or item.get("is_discarded"):
                continue
            if str(item.get("agent_version_id") or "") == winner_version:
                score = _as_float(race.get("winner_score"))
                if score is not None:
                    return _agent_label(item), score
    winner_name = str(race.get("winner_agent_name") or "").strip()
    winner_score = _as_float(race.get("winner_score"))
    if winner_name and winner_score is not None:
        return winner_name.replace(" ", "_"), winner_score
    for item in qualifiers:
        if not isinstance(item, dict) or item.get("is_discarded"):
            continue
        if _item_race_rank(item) == 1:
            score = _qualifier_race_score(item, number)
            if score is not None:
                return _agent_label(item), score
    return _winner_from_race(race)


def _winner_from_race(race: dict) -> tuple[str | None, float | None]:
    name = race.get("winner_agent_name") or race.get("race_agent")
    label = str(name).replace(" ", "_") if name else None
    return label, _as_float(race.get("winner_score") if race.get("winner_score") is not None else race.get("race_score"))


def _fill_overall(row: dict) -> dict:
        return row


def _qualifier_race_score(item: dict, race_number: int | None = None) -> float | None:
    for value in (item.get("race_score"), item.get("raw_score"), item.get("score")):
        score = _as_float(value)
        if score is not None:
            return score
    for entry in _window_list(item):
        if race_number is not None and _race_num(entry.get("race_number")) != race_number:
            continue
        raw = _window_raw(entry)
        if raw is not None:
            return raw
    return None


def _top_half_anchor(qualifiers: list[dict], race_number: int | None = None) -> float | None:
    scores: list[float] = []
    for item in qualifiers:
        if item.get("is_discarded"):
            continue
        score = _qualifier_race_score(item, race_number)
        if score is not None:
            scores.append(score)
    if not scores:
        return None
    scores.sort(reverse=True)
    half = scores[: max(1, len(scores) // 2)]
    return round(sum(half) / len(half), 4)


def _race_anchor(race: dict, qualifiers: list[dict]) -> float | None:
    race_id = str(race.get("race_id") or "")
    try:
        number = int(race.get("race_number")) if race.get("race_number") is not None else None
    except (TypeError, ValueError):
        number = None
    for item in qualifiers:
        window = item.get("window") if isinstance(item.get("window"), list) else []
        for point in window:
            if not isinstance(point, dict):
                continue
            point_id = str(point.get("race_id") or "")
            try:
                point_num = int(point.get("race_number")) if point.get("race_number") is not None else None
            except (TypeError, ValueError):
                point_num = None
            if race_id and point_id == race_id:
                anchor = _as_float(point.get("anchor"))
                if anchor is not None:
                    return anchor
            if number is not None and point_num == number:
                anchor = _as_float(point.get("anchor"))
                if anchor is not None:
                    return anchor
    computed = _top_half_anchor(qualifiers, number)
    if computed is not None:
        return computed
    return _as_float(race.get("challenge_threshold") or race.get("anchor"))


def _current_race_field_anchor(
    race: dict,
    qualifiers: list[dict] | None = None,
    live_scores: dict[str, float] | None = None,
) -> float | None:
    number = _race_num(race.get("race_number"))
    race_id = str(race.get("race_id") or "")
    for value in (
        _as_float(race.get("anchor")),
        _as_float(race.get("challenge_threshold")),
        _as_float(race.get("top50_mean")),
    ):
        if value is not None:
            return value
    rows = [item for item in (qualifiers or []) if isinstance(item, dict)]
    for item in rows:
        for entry in _window_list(item):
            if race_id and str(entry.get("race_id") or "") == race_id:
                anchor = _as_float(entry.get("anchor"))
                if anchor is not None:
                    return anchor
            if number is not None and _race_num(entry.get("race_number")) == number:
                anchor = _as_float(entry.get("anchor"))
                if anchor is not None:
                    return anchor
    scored = []
    for item in rows:
        version_id = str(item.get("agent_version_id") or "")
        score = _as_float((live_scores or {}).get(version_id))
        if score is None:
            score = _qualifier_race_score(item, number)
        if score is not None:
            scored.append({**item, "race_score": score})
    return _top_half_anchor(scored, number)


def _top_fraction_slice(values: list[float], fraction: float) -> list[float]:
    ranked = sorted(values, reverse=True)
    count = max(1, math.ceil(len(ranked) * fraction))
    return ranked[:count]


def _top_fraction_mean(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    top = _top_fraction_slice(values, fraction)
    return round(sum(top) / len(top), 4)


def _top_fraction_median(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    top = sorted(_top_fraction_slice(values, fraction))
    mid = len(top) // 2
    if len(top) % 2:
        return round(top[mid], 4)
    return round((top[mid - 1] + top[mid]) / 2, 4)


def _reduce_scores(
    values: list[float], fraction: float | None = None, *, median: bool = False
) -> float | None:
    if not values:
        return None
    if fraction is None:
        if median:
            ranked = sorted(values)
            mid = len(ranked) // 2
            if len(ranked) % 2:
                return round(ranked[mid], 4)
            return round((ranked[mid - 1] + ranked[mid]) / 2, 4)
        return round(sum(values) / len(values), 4)
    if median:
        return _top_fraction_median(values, fraction)
    return _top_fraction_mean(values, fraction)


def _mean_qualifier_field(
    items: list[dict],
    keys: tuple[str, ...],
    fraction: float | None = None,
    *,
    median: bool = False,
) -> float | None:
    values: list[float] = []
    for item in items:
        if item.get("is_discarded"):
            continue
        score = None
        for key in keys:
            score = _as_float(item.get(key))
            if score is not None:
                break
        if score is not None:
            values.append(score)
    return _reduce_scores(values, fraction, median=median)


def _mean_race_field(
    items: list[dict],
    race: dict,
    fraction: float | None = 0.35,
    *,
    median: bool = False,
) -> float | None:
    number = _race_num(race.get("race_number"))
    values: list[float] = []
    for item in items:
        if item.get("is_discarded"):
            continue
        score = _qualifier_race_score(item, number)
        if score is not None:
            values.append(score)
    return _reduce_scores(values, fraction, median=median)


def _race_averages(race: dict, items: list[dict], race_id: str = "") -> dict:
    del race_id
    return {
        "overall_mid": _mean_qualifier_field(
            items, ("weighted_score", "overall_score", "qualifying_score"), 0.35, median=True
        ),
        "race_mid": _mean_race_field(items, race, 0.35, median=True),
        "p_mid": _mean_qualifier_field(
            items, ("product", "product_score", "p_score"), 0.35, median=True
        ),
        "s_mid": _mean_qualifier_field(
            items, ("shop", "shop_score", "s_score"), 0.35, median=True
        ),
        "v_mid": _mean_qualifier_field(
            items, ("voucher", "voucher_score", "v_score"), 0.35, median=True
        ),
    }


def _row_agent_label(row: dict) -> str | None:
    name = str(row.get("agent_name") or "").replace(" ", "_")
    if not name:
        return None
    version = row.get("version_number")
    if version is None or version == "":
        return name
    return f"{name}_v{version}"


def _top_stored_row(rows: list[dict], key: str) -> tuple[str | None, float | None]:
    best = None
    best_score = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        score = _as_float(row.get(key))
        if score is None:
            continue
        if best_score is None or score > best_score:
            best_score = score
            best = row
    if best is None:
        return None, None
    return _row_agent_label(best), best_score


def _top_stored_race_leader(rows: list[dict]) -> tuple[str | None, float | None]:
    """Race-card leader: highest race_score on the race table."""
    return _top_stored_row(rows, "race_score")


def _leader_rows_for(summary: dict) -> list[dict]:
    race_id = str(summary.get("race_id") or "")
    number = _race_num(summary.get("race_number"))
    rows: list[dict] = []
    status = str(summary.get("status") or "").upper()
    if race_id:
        try:
            table = store.load_race_table(race_id)
        except Exception:
            table = None
        if table and table.get("rows"):
            rows = [row for row in table["rows"] if isinstance(row, dict)]
        needs_refresh = False
        if not rows:
            needs_refresh = status in {
                "RACE_COMPLETE",
                "COMPLETED",
                "FINISHED",
                "CLOSED",
                "LIVE_RANKING",
                "RACE_RUNNING",
            }
        elif not any(
            _as_float(row.get("race_score")) is not None or _as_float(row.get("overall_score")) is not None
            for row in rows
        ):
            needs_refresh = status in {
                "RACE_COMPLETE",
                "COMPLETED",
                "FINISHED",
                "CLOSED",
                "LIVE_RANKING",
                "RACE_RUNNING",
            }
        if needs_refresh:
            try:
                from . import race_table as race_table_mod

                table = race_table_mod.get_race_table(race_id)
                if table and table.get("rows"):
                    rows = [row for row in table["rows"] if isinstance(row, dict)]
            except Exception:
                pass
    has_scores = any(
        _as_float(row.get("overall_score")) is not None or _as_float(row.get("race_score")) is not None
        for row in rows
    )
    if has_scores:
        return rows
    try:
        standings = store.load_current_standings() or {}
    except Exception:
        standings = {}
    if _race_num(standings.get("race_number")) == number:
        return [row for row in (standings.get("rows") or []) if isinstance(row, dict)]
    return rows


def _apply_stored_leaders(summary: dict) -> dict:
    rows = _leader_rows_for(summary)
    out = {**summary}
    if rows:
        overall_agent, overall_score = _top_stored_row(rows, "overall_score")
        race_agent, race_score = _top_stored_race_leader(rows)
        changed = False
        if overall_agent:
            if out.get("overall_agent") != overall_agent or _as_float(out.get("overall_score")) != overall_score:
                changed = True
            out["overall_agent"] = overall_agent
            out["overall_score"] = overall_score
        if race_agent:
            if out.get("race_agent") != race_agent or _as_float(out.get("race_score")) != race_score:
                changed = True
            out["race_agent"] = race_agent
            out["race_score"] = race_score
        if changed:
            try:
                store.save_race_summary(out)
            except Exception:
                pass
    # Heal completed races whose summary still has a blank Race leader.
    status = str(out.get("status") or "").upper()
    race_id = str(out.get("race_id") or "")
    if (
        race_id
        and out.get("race_score") is None
        and status in {"RACE_COMPLETE", "COMPLETED", "FINISHED", "CLOSED", "LIVE_RANKING"}
    ):
        try:
            wrap = _fetch_race_wrap(race_id)
        except Exception:
            wrap = {}
        if wrap:
            race = wrap.get("race") if isinstance(wrap.get("race"), dict) else {}
            if not isinstance(race, dict):
                race = {}
            healed = _summarize_race(race, wrap.get("qualifiers"), False, use_stored=False)
            if healed.get("race_score") is not None:
                out["race_agent"] = healed.get("race_agent")
                out["race_score"] = healed.get("race_score")
            if out.get("overall_score") is None and healed.get("overall_score") is not None:
                out["overall_agent"] = healed.get("overall_agent")
                out["overall_score"] = healed.get("overall_score")
            if healed.get("agent_count"):
                out["agent_count"] = healed.get("agent_count")
            try:
                store.save_race_summary(out)
            except Exception:
                pass
    if out.get("agent_count") in (None, 0) and rows:
        out["agent_count"] = len(rows)
    if out.get("race_threshold") is None:
        field = _stored_race_anchor(out.get("race_number"))
        if field is not None:
            out["race_threshold"] = field
    return out


def _summarize_race(
    race: dict, qualifiers: object, is_latest: bool, *, use_stored: bool = True
) -> dict:
    items = [item for item in qualifiers if isinstance(item, dict)] if isinstance(qualifiers, list) else []
    overall_agent, overall_score = _top_by(items, "weighted_score")
    status = str(race.get("status") or "").upper()
    if overall_agent is None and status not in _RACE_SCORED_STATUS:
        overall_agent, overall_score = _top_by(items, "qualifying_score")
    race_agent, race_score = _race_top(items, race)
    count = len(items) if items else int(race.get("qualifier_count") or 0)
    race_id = str(race.get("race_id") or "")
    row = {
        "race_id": race_id,
        "race_number": race.get("race_number"),
        "status": race.get("status"),
        "is_latest": is_latest,
        "agent_count": count,
        "completed_at": race.get("race_completed_at") or race.get("completed_at"),
        "overall_agent": overall_agent,
        "overall_score": overall_score,
        "race_agent": race_agent,
        "race_score": race_score,
        "race_threshold": _race_anchor(race, items),
        "qualifying_threshold": _as_float(race.get("qualifying_threshold")),
        "suite_id": race.get("suite_id"),
        "score_mode": store.score_mode_for(race),
        **_race_averages(race, items, race_id),
    }
    return _apply_stored_leaders(row) if use_stored else row


def _race_from_wrap(wrap: dict, fallback: dict | None, is_latest: bool) -> dict:
    race = wrap.get("race") if isinstance(wrap.get("race"), dict) else fallback
    if not isinstance(race, dict):
        race = fallback or {}
    return _summarize_race(race, wrap.get("qualifiers"), is_latest)


def _history_shell(item: dict) -> dict:
    race_id = str(item.get("race_id") or "")
    cached = _race_summaries.get(race_id)
    shell = _summarize_race(item, [], False)
    if not cached:
        return shell
    merged = _fill_overall(
            {
                **cached,
                "race_number": item.get("race_number", cached.get("race_number")),
                "status": item.get("status", cached.get("status")),
                "agent_count": cached.get("agent_count") or int(item.get("qualifier_count") or 0),
            "completed_at": cached.get("completed_at")
            or item.get("race_completed_at")
            or item.get("completed_at"),
                "is_latest": False,
            }
        )
    if not merged.get("overall_agent"):
        merged["overall_agent"] = shell.get("overall_agent")
        merged["overall_score"] = shell.get("overall_score")
    if not merged.get("race_agent"):
        merged["race_agent"] = shell.get("race_agent")
        merged["race_score"] = shell.get("race_score")
    return _fill_overall(merged)


def _fetch_history_summary(item: dict) -> dict:
    race_id = str(item.get("race_id") or "")
    wrap: dict = {}
    for attempt in range(3):
        try:
            payload = _fetch_json(f"{ORO_BASE}/races/{race_id}", timeout=25)
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            OSError,
            json.JSONDecodeError,
        ):
            payload = {}
        if isinstance(payload, dict) and (payload.get("qualifiers") or payload.get("race")):
            wrap = payload
            break
        time.sleep(0.5 * (attempt + 1))
    return _race_from_wrap(wrap, item, False)


def _enrich_history(items: list[dict]) -> None:
    global _enrich_running, _races_cache
    try:
        if not items:
            return
        with ThreadPoolExecutor(max_workers=min(12, len(items))) as pool:
            summaries = list(pool.map(_fetch_history_summary, items))
        with _races_lock:
            for summary in summaries:
                race_id = str(summary.get("race_id") or "")
                if not race_id:
                    continue
                _race_summaries[race_id] = summary
                store.save_race_summary(summary)
            if _races_cache:
                stamp, payload = _races_cache
                by_id = {
                    str(summary.get("race_id") or ""): summary
                    for summary in summaries
                    if summary.get("race_id")
                }
                for row in payload.get("rows") or []:
                    extra = by_id.get(str(row.get("race_id") or ""))
                    if not extra:
                        continue
                    latest = bool(row.get("is_latest"))
                    row.update(extra)
                    row["is_latest"] = latest
                _races_cache = (stamp, payload)
    finally:
        with _races_lock:
            _enrich_running = False


def _start_enrich(items: list[dict]) -> None:
    global _enrich_running
    if not items:
        return
    with _races_lock:
        if _enrich_running:
            return
        _enrich_running = True
    threading.Thread(target=_enrich_history, args=(items,), daemon=True).start()


UPDATE_RACE_LIMIT = 2
INFO_MIN_RACE = 100


def _race_recency_key(row: dict) -> tuple[str, str, int]:
    completed = str(row.get("completed_at") or row.get("race_completed_at") or "")
    created = str(row.get("created_at") or "")
    return (completed, created, _race_num(row.get("race_number")) or 0)


def _is_legacy_season(item: dict) -> bool:
    if store.is_tf_race(item):
        return False
    number = _race_num(item.get("race_number"))
    return number is not None and number < INFO_MIN_RACE


def _fetch_history_page(offset: int, limit: int) -> dict:
    return _fetch_json(
        f"{ORO_BASE}/races/history?limit={limit}&offset={offset}",
        timeout=20,
        quick=False,
    )


def _current_race_meta() -> tuple[str, object, str]:
    try:
        wrap = _fetch_json(f"{ORO_BASE}/races/current", timeout=20, quick=False)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        return "", None, ""
    race = wrap.get("race") if isinstance(wrap.get("race"), dict) else wrap
    if not isinstance(race, dict):
        return "", None, ""
    return (
        str(race.get("race_id") or ""),
        race.get("race_number"),
        str(race.get("status") or "").upper(),
    )


def _latest_finished_history(limit: int = UPDATE_RACE_LIMIT) -> list[dict]:
    current_id, _current_number, current_status = _current_race_meta()
    items: list[dict] = []
    seen: set[str] = set()
    offset = 0
    page_size = max(10, limit * 5)
    while offset < page_size:
        try:
            history = _fetch_history_page(offset, page_size)
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            OSError,
            json.JSONDecodeError,
        ):
            break
        batch = history.get("races") if isinstance(history, dict) else None
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            if not isinstance(item, dict):
                continue
            race_id = str(item.get("race_id") or "")
            status = str(item.get("status") or "").upper()
            if not race_id or race_id in seen:
                continue
            if race_id == current_id and current_status in _LIVE_STATUS:
                continue
            if status in _LIVE_STATUS:
                continue
            items.append(item)
            seen.add(race_id)
        offset += len(batch)
        total = history.get("total")
        if isinstance(total, int) and offset >= total:
            break
        if len(batch) < page_size:
            break
        if len(items) >= limit:
            break
    items.sort(key=_race_recency_key, reverse=True)
    if len(items) < limit:
        stored = store.load_all_race_summaries()
        extras = sorted(
            stored.values(),
            key=_race_recency_key,
            reverse=True,
        )
        if current_id:
            seen.add(current_id)
        for row in extras:
            race_id = str(row.get("race_id") or "")
            if not race_id or race_id in seen:
                continue
            if str(row.get("status") or "").upper() in _LIVE_STATUS:
                continue
            items.append(
                {
                    "race_id": race_id,
                    "race_number": row.get("race_number"),
                    "status": row.get("status"),
                }
            )
            seen.add(race_id)
            if len(items) >= limit:
                break
    return items[:limit]


def _set_update_progress(*, active: bool | None = None, race_number: object = None) -> None:
    global _progress_active, _progress_race_number
    with _progress_lock:
        if active is not None:
            _progress_active = active
            if not active:
                _progress_race_number = None
                return
        if race_number is None:
            return
        try:
            _progress_race_number = int(race_number)
        except (TypeError, ValueError):
            return


def get_races_update_progress() -> dict:
    with _progress_lock:
        number = _progress_race_number
        active = _progress_active
    return {
        "updating": active,
        "race_number": number,
        "text": f"Race #{number} data is loading" if number is not None else "",
    }


def _wrap_race_number(wrap: dict, fallback: dict | None) -> object:
    race = wrap.get("race") if isinstance(wrap.get("race"), dict) else wrap
    if isinstance(race, dict) and race.get("race_number") is not None:
        return race.get("race_number")
    if isinstance(fallback, dict):
        return fallback.get("race_number")
    return None


def _fetch_race_wrap(race_id: str) -> dict:
    url = f"{ORO_BASE}/races/{race_id}"
    for attempt in range(3):
        try:
            wrap = _fetch_json(url, timeout=25, quick=False)
            if wrap and (wrap.get("qualifiers") or wrap.get("race")):
                return wrap
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
            time.sleep(0.8 * (attempt + 1))
    return {}


def _ingest_races_and_tables(
    current_id: str,
    current_wrap: dict,
    history_items: list[dict],
    *,
    info_progress: bool = False,
) -> None:
    from . import race_table as race_table_mod

    jobs: list[tuple[str, object, dict | None, dict | None]] = []
    if current_id:
        jobs.append((current_id, _wrap_race_number(current_wrap, None), current_wrap, None))
    for item in history_items:
        race_id = str(item.get("race_id") or "")
        if not race_id or race_id == current_id:
            continue
        jobs.append((race_id, item.get("race_number"), None, item))
    jobs.sort(key=lambda item: item[1] or 0, reverse=True)

    def _mark(number: object) -> None:
        if info_progress:
            _set_info_progress(number)
        else:
            _set_update_progress(race_number=number)

    for race_id, number, wrap, fallback in jobs:
        _mark(number)
        if not wrap or not (wrap.get("qualifiers") or wrap.get("race")):
            wrap = _fetch_race_wrap(race_id)
        if not wrap:
            continue
        if number is None:
            number = _wrap_race_number(wrap, fallback)
            _mark(number)
        race = wrap.get("race") if isinstance(wrap.get("race"), dict) else fallback or {}
        if not isinstance(race, dict):
            race = fallback or {}
        summary = _summarize_race(
            race, wrap.get("qualifiers"), race_id == current_id, use_stored=False
        )
        if not summary.get("race_id"):
            summary["race_id"] = race_id
        if summary.get("race_id"):
            store.save_race_summary(summary)
            _race_summaries[race_id] = {**summary, "is_latest": False}
            field = _as_float(summary.get("race_threshold"))
            race_number = _race_num(summary.get("race_number"))
            if race_number is not None and field is not None:
                try:
                    store.save_race_thresholds({race_number: field})
                except Exception:
                    pass
        table = race_table_mod.ingest_race_wrap(race_id, wrap, start_enrich=False)
        rows = [row for row in (table.get("rows") or []) if isinstance(row, dict)]
        if rows:
            try:
                race_table_mod.apply_code_meta(rows)
            except Exception:
                pass
            store.save_race_table({**table, "rows": rows}, False)
            if not info_progress:
                try:
                    race_table_mod.apply_psv_scores(rows, race_id, top_fraction=None)
                except Exception:
                    pass
                store.save_race_table({**table, "rows": rows}, False)
            avgs = store.averages_from_rows(rows)
            avg_keys = (
                ("overall_mid", "race_mid")
                if info_progress
                else ("overall_mid", "race_mid", "p_mid", "s_mid", "v_mid", *store.TF_MID_KEYS)
            )
            for key in avg_keys:
                if avgs.get(key) is not None:
                    summary[key] = avgs[key]
        if info_progress:
            summary.pop("p_mid", None)
            summary.pop("s_mid", None)
            summary.pop("v_mid", None)
            summary.pop("p_avg", None)
            summary.pop("s_avg", None)
            summary.pop("v_avg", None)
            for key in store.TF_MID_KEYS:
                summary.pop(key, None)
                summary.pop(key.replace("_mid", "_avg"), None)
        summary = _apply_stored_leaders({**summary, "race_id": race_id})
        store.save_race_summary(summary)
        _race_summaries[race_id] = {**summary, "is_latest": False}


_list_collect_lock = threading.Lock()


def _list_from_stored(stored: dict[str, dict]) -> dict:
    rows = []
    live_id = None
    averages = store.load_race_averages(list(stored))
    for race_id, summary in stored.items():
        avgs = averages.get(race_id) or {}
        merged = {**summary, "race_id": race_id, "is_latest": False}
        persist_psv = False
        for key in ("overall_mid", "race_mid", "p_mid", "s_mid", "v_mid", *store.TF_MID_KEYS):
            if avgs.get(key) is not None:
                merged[key] = avgs[key]
                if key in ("p_mid", "s_mid", "v_mid", *store.TF_MID_KEYS) and summary.get(key) is None:
                    persist_psv = True
        if persist_psv:
            store.save_race_psv_averages(race_id, merged)
        merged["score_mode"] = store.score_mode_for(merged)
        row = _apply_stored_leaders(_fill_overall(merged))
        rows.append(row)
        status = str(row.get("status") or "").upper()
        if status in _LIVE_STATUS:
            if live_id is None or _race_recency_key(row) >= _race_recency_key(
                next((item for item in rows if item.get("race_id") == live_id), {})
            ):
                live_id = race_id
    rows.sort(key=_race_recency_key, reverse=True)
    latest = live_id or (rows[0].get("race_id") if rows else None)
    for row in rows:
        row["is_latest"] = row.get("race_id") == latest
    selected = next((row["race_id"] for row in rows if not row.get("is_latest")), latest)
    return {"rows": rows, "selected_id": selected}


def _oro_list_row(item: dict) -> dict:
    race_id = str(item.get("race_id") or "")
    wrap = _fetch_race_wrap(race_id) if race_id else {}
    race = wrap.get("race") if isinstance(wrap.get("race"), dict) else item
    if not isinstance(race, dict):
        race = item
    return _summarize_race(race, wrap.get("qualifiers"), False, use_stored=False)


def _list_from_oro() -> dict:
    items = _finished_races_from(INFO_MIN_RACE)
    summaries: list[dict] = []
    if items:
        with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
            summaries = list(pool.map(_oro_list_row, items))
    rows = [row for row in summaries if isinstance(row, dict) and row.get("race_id")]
    rows.sort(key=_race_recency_key, reverse=True)
    latest = rows[0]["race_id"] if rows else None
    for index, row in enumerate(rows):
        row["is_latest"] = index == 0
    selected = next((row["race_id"] for row in rows if not row.get("is_latest")), latest)
    return {"rows": rows, "selected_id": selected}


def get_races_list() -> dict:
    return _list_from_stored(store.load_all_race_summaries())


def _run_update_race_database(race_id: str) -> None:
    try:
        with _list_collect_lock:
            stored = store.load_race_summary(race_id) or {}
            item = {
                "race_id": race_id,
                "race_number": stored.get("race_number"),
                "status": stored.get("status"),
                "completed_at": stored.get("completed_at"),
            }
            _set_update_progress(race_number=stored.get("race_number"))
            _ingest_races_and_tables("", {}, [item])
    finally:
        _set_update_progress(active=False)


def start_update_race_database(race_id: str = "") -> dict:
    race_id = str(race_id or "").strip()
    if not race_id:
        return {**get_races_update_progress(), "ok": False, "error": "Update Race Info!"}
    stored = store.load_race_summary(race_id) or {}
    with _progress_lock:
        already = _progress_active
    if not already:
        _set_update_progress(active=True, race_number=stored.get("race_number"))
        threading.Thread(
            target=_run_update_race_database,
            args=(race_id,),
            daemon=True,
            name="oro-updatedb",
        ).start()
    return {**get_races_update_progress(), "ok": True}


def update_race_database(race_id: str = "") -> dict:
    return start_update_race_database(race_id)


_info_lock = threading.Lock()
_info_active = False
_info_race_number: int | None = None


def get_races_info_progress() -> dict:
    with _info_lock:
        number = _info_race_number
        active = _info_active
    return {
        "updating": active,
        "race_number": number,
        "text": f"Race #{number} info is loading" if number is not None else "",
        "ok": True,
    }


def _set_info_progress(race_number: object = None) -> None:
    global _info_race_number
    with _info_lock:
        if race_number is None:
            _info_race_number = None
            return
        try:
            _info_race_number = int(race_number)
        except (TypeError, ValueError):
            return


def _finished_races_from(min_number: int = INFO_MIN_RACE) -> list[dict]:
    current_id, _current_number, current_status = _current_race_meta()
    items: list[dict] = []
    seen: set[str] = set()
    offset = 0
    page_size = 100
    while True:
        try:
            history = _fetch_history_page(offset, page_size)
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            OSError,
            json.JSONDecodeError,
        ):
            break
        batch = history.get("races") if isinstance(history, dict) else None
        if not isinstance(batch, list) or not batch:
            break
        reached_older = False
        for item in batch:
            if not isinstance(item, dict):
                continue
            race_id = str(item.get("race_id") or "")
            status = str(item.get("status") or "").upper()
            number = _race_num(item.get("race_number"))
            if not race_id or race_id in seen:
                continue
            if _is_legacy_season(item):
                reached_older = True
                continue
            if race_id == current_id and current_status in _LIVE_STATUS:
                continue
            if status in _LIVE_STATUS:
                continue
            items.append(item)
            seen.add(race_id)
        offset += len(batch)
        if reached_older:
            break
        total = history.get("total")
        if isinstance(total, int) and offset >= total:
            break
        if len(batch) < page_size:
            break
    items.sort(key=_race_recency_key, reverse=True)
    return items


def _store_info_summary(item: dict) -> None:
    _set_info_progress(item.get("race_number"))
    race_id = str(item.get("race_id") or "")
    wrap = _fetch_race_wrap(race_id) if race_id else {}
    race = wrap.get("race") if isinstance(wrap.get("race"), dict) else item
    if not isinstance(race, dict):
        race = item
    quals = [row for row in (wrap.get("qualifiers") or []) if isinstance(row, dict)]
    summary = _summarize_race(race, quals, False, use_stored=False)
    race_id = str(summary.get("race_id") or race_id or "")
    if not race_id:
        return
    summary["race_id"] = race_id
    summary["overall_mid"] = _mean_qualifier_field(
        quals, ("weighted_score", "overall_score", "qualifying_score"), 0.35, median=True
    )
    summary["race_mid"] = _mean_race_field(quals, race, 0.35, median=True)
    summary.pop("p_mid", None)
    summary.pop("s_mid", None)
    summary.pop("v_mid", None)
    summary.pop("p_avg", None)
    summary.pop("s_avg", None)
    summary.pop("v_avg", None)
    store.save_race_summary(summary)
    _race_summaries[race_id] = {**summary, "is_latest": False}


def _run_update_races_info() -> None:
    global _info_active, _races_cache
    try:
        with _races_lock:
            _races_cache = None
        items = _finished_races_from(INFO_MIN_RACE)
        if items:
            with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
                list(pool.map(_store_info_summary, items))
    finally:
        _set_info_progress(None)
        with _info_lock:
            _info_active = False


def start_update_races_info() -> dict:
    global _info_active
    with _info_lock:
        already = _info_active
        if not already:
            _info_active = True
            threading.Thread(
                target=_run_update_races_info,
                daemon=True,
                name="oro-races-info",
            ).start()
    return get_races_info_progress()


def _collect_races_list(*, refresh: bool = False) -> dict:
    global _races_cache
    stored = store.load_all_race_summaries()
    if refresh:
        for race_id, summary in stored.items():
            _race_summaries.setdefault(race_id, {**summary, "is_latest": False})
        with _races_lock:
            _races_cache = None
        latest = _latest_finished_history(UPDATE_RACE_LIMIT)
        _ingest_races_and_tables("", {}, latest[:UPDATE_RACE_LIMIT])
        stored = store.load_all_race_summaries()
        if stored:
            return _list_from_stored(stored)
        return {"rows": [], "selected_id": None}
    payload = {"rows": [], "selected_id": None}
    current_id = ""
    current_wrap: dict = {}
    history_items: list[dict] = []
    try:
        current_wrap = _fetch_json(f"{ORO_BASE}/races/current", timeout=20)
        current = (
            current_wrap.get("race")
            if isinstance(current_wrap.get("race"), dict)
            else current_wrap
        )
        current_id = str(current.get("race_id") or "")
        if current_id:
            current_row = _race_from_wrap(current_wrap, current, True)
            _race_summaries[current_id] = {**current_row, "is_latest": False}
            store.save_race_summary({**current_row, "is_latest": False})
            _set_update_progress(race_number=current_row.get("race_number"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        current_id = ""

    offset = 0
    page_size = 100
    while True:
        try:
            history = _fetch_history_page(offset, page_size)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
            break
        batch = history.get("races") if isinstance(history, dict) else None
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            if not isinstance(item, dict):
                continue
            race_id = str(item.get("race_id") or "")
            if not race_id or race_id == current_id:
                continue
            history_items.append(item)
        offset += len(batch)
        total = history.get("total")
        if isinstance(total, int) and offset >= total:
            break
        if len(batch) < page_size:
            break

    rows: list[dict] = []
    seen: set[str] = set()
    if current_id:
        current_row = _race_summaries.get(current_id) or stored.get(current_id)
        if current_row:
            rows.append(_fill_overall({**current_row, "is_latest": True, "race_id": current_id}))
            seen.add(current_id)
    for item in history_items:
        row = _history_shell(item)
        race_id = str(row.get("race_id") or "")
        if not race_id or race_id in seen:
            continue
        rows.append(_fill_overall(row))
        seen.add(race_id)
    for race_id, summary in stored.items():
        if race_id in seen:
            continue
        rows.append(
            _fill_overall({**summary, "is_latest": race_id == current_id, "race_id": race_id})
        )
        seen.add(race_id)
    rows = [row for row in rows if row.get("race_id")]
    rows.sort(key=lambda row: row.get("race_number") or 0, reverse=True)
    for row in rows:
        if row.get("overall_agent") and not (stored.get(str(row.get("race_id") or "")) or {}).get("overall_agent"):
            store.save_race_summary(row)
            _race_summaries[str(row["race_id"])] = {**row, "is_latest": False}
    payload = {
        "rows": rows,
        "selected_id": current_id or (rows[0]["race_id"] if rows else None),
    }
    missing = []
    for item in history_items:
        race_id = str(item.get("race_id") or "")
        cached = _race_summaries.get(race_id) or stored.get(race_id) or {}
        if (
            cached.get("overall_agent") is None
            or cached.get("race_agent") is None
        ):
            missing.append(item)
    if not rows:
        with _races_lock:
            if _races_cache:
                return _races_cache[1]
        return payload

    with _races_lock:
        _races_cache = (time.monotonic(), payload)
    _start_enrich(missing)
    return payload

