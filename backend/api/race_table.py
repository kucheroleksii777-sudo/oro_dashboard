import io
import json
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from . import store
from .network import USER_AGENT
from .neurons import peek_registered_uids
from .oro import ORO_BASE, _as_float, _fetch_any, _fetch_json

CACHE_SECONDS = 0
_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}
_status: dict[str, dict] = {}
_cells: dict[str, dict[str, dict]] = {}
_lines: dict[str, int | None] = {}
_code: dict[str, dict] = {}
_race_counts: dict[str, int] = {}
_overflow_numbers: dict[str, list[int]] = {}
_race_number_by_id: dict[str, int] = {}
_history_numbers_loaded = False
_fetched_cells: set[tuple[str, str]] = set()
_enriching: set[str] = set()
_collect_meta = threading.Lock()
_collect_locks: dict[str, threading.Lock] = {}


def _collect_lock(race_id: str) -> threading.Lock:
    with _collect_meta:
        lock = _collect_locks.get(race_id)
        if lock is None:
            lock = threading.Lock()
            _collect_locks[race_id] = lock
        return lock


def _leader_version_ids(rows: list[dict]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    def add(row: dict | None) -> None:
        if not isinstance(row, dict):
            return
        version_id = str(row.get("agent_version_id") or "")
        if not version_id or version_id in seen:
            return
        seen.add(version_id)
        ids.append(version_id)

    scored = [row for row in rows if isinstance(row, dict)]
    if scored:
        add(max(scored, key=lambda row: _as_float(row.get("overall_score")) or -1))
        add(max(scored, key=lambda row: _as_float(row.get("race_score")) or -1))
        for row in scored:
            if row.get("rank") == 1:
                add(row)
    return ids


def _refresh_private_leaders(rows: list[dict]) -> bool:
    changed = False
    for version_id in _leader_version_ids(rows):
        current = next(
            (
                row
                for row in rows
                if str(row.get("agent_version_id") or "") == version_id
            ),
            None,
        )
        if not current or current.get("code") == "public":
            continue
        fresh = _fetch_status(version_id)
        if fresh.get("code") != "public":
            continue
        current["code"] = "public"
        current["submitted_at"] = fresh.get("submitted_at") or current.get("submitted_at")
        if current.get("lines") is None:
            current["lines"] = _fetch_lines(version_id, True)
        changed = True
    return changed


def _table_from_store(stored: dict) -> dict:
    raw = [row for row in stored.get("rows") or [] if isinstance(row, dict)]
    status, lines, cells, counts, overflow = store.load_agents(
        [str(row.get("agent_version_id") or "") for row in raw]
    )
    race_id = str(stored.get("race_id") or "")
    rows = []
    for row in raw:
        version_id = str(row.get("agent_version_id") or "")
        item = _with_psv_scores(row, (cells.get(version_id) or {}).get(race_id) or {})
        agent = status.get(version_id) or {}
        item["code"] = agent.get("code") or item.get("code") or "private"
        if item["code"] == "public":
            item["lines"] = item.get("lines") if item.get("lines") is not None else lines.get(version_id)
        else:
            item["lines"] = None
        item["submitted_at"] = _utc_iso(agent.get("submitted_at")) or item.get("submitted_at")
        _apply_overflow_races(item, through=stored.get("race_number"))
        item["eliminated"] = bool(
            item.get("eliminated") or item.get("eliminated_at") or item.get("is_discarded")
        )
        rows.append(item)
    index = store.load_race_score_index()
    current_number = stored.get("race_number")
    id_by_number: dict[int, str] = {}
    for summary in store.load_all_race_summaries().values():
        number = _race_int(summary.get("race_number"))
        race_id = str(summary.get("race_id") or "")
        if number is not None and race_id:
            id_by_number[number] = race_id
    threshold = _as_float(stored.get("race_threshold"))
    if threshold is None:
        summary = store.load_race_summary(str(stored.get("race_id") or "")) or {}
        threshold = _as_float(summary.get("race_threshold"))
    if threshold is None:
        number = _race_int(stored.get("race_number"))
        if number is not None:
            try:
                threshold = _as_float(store.load_race_thresholds().get(number))
            except Exception:
                threshold = None
    for item in rows:
        item["races"] = _races_with_scores(
            item,
            index,
            current_number,
            cells=cells,
            id_by_number=id_by_number,
        )
        score = _as_float(item.get("race_score"))
        item["margin"] = (
            round((score - threshold) * 100, 2)
            if score is not None and threshold is not None
            else None
        )
    if _refresh_private_leaders(rows):
        by_id = {
            str(row.get("agent_version_id") or ""): row
            for row in rows
            if row.get("agent_version_id")
        }
        for row in raw:
            fresh = by_id.get(str(row.get("agent_version_id") or ""))
            if not fresh or fresh.get("code") != "public":
                continue
            row["code"] = "public"
            if fresh.get("lines") is not None:
                row["lines"] = fresh.get("lines")
            if fresh.get("submitted_at"):
                row["submitted_at"] = fresh.get("submitted_at")
        try:
            store.save_race_table(
                {
                    "race_id": stored.get("race_id"),
                    "race_number": stored.get("race_number"),
                    "rows": raw,
                },
                bool(stored.get("enriched")),
            )
        except Exception:
            pass
    return {
        "race_id": stored.get("race_id"),
        "race_number": stored.get("race_number"),
        "score_mode": store.score_mode_for(store.load_race_summary(str(stored.get("race_id") or "")) or stored),
        "race_threshold": threshold,
        "total": stored.get("total") or len(rows),
        "rows": rows,
        "updated_at": stored.get("updated_at"),
    }


def _utc_iso(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return value.strip()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _empty(race_id: str) -> dict:
    return {
        "race_id": race_id,
        "race_number": None,
        "total": 0,
        "rows": [],
        "updated_at": None,
    }


def _problem_index(item: dict) -> int | None:
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    title = str(meta.get("title") or item.get("title") or "").strip()
    if title:
        tail = title.rsplit(" ", 1)[-1]
        if tail.isdigit():
            number = int(tail)
            if 1 <= number <= 30:
                return number
    for key in ("index", "problem_index", "problem_number", "number"):
        raw = item.get(key)
        if raw is None:
            raw = meta.get(key)
        try:
            number = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 30:
            return number
    return None


def _result_status(item: dict) -> str:
    return str(item.get("status") or "").upper().replace(" ", "_")


def _validator_items(results: object) -> list[dict]:
    raw = [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []
    by_key: dict[str, dict] = {}
    for item in raw:
        key = str(item.get("validator_hotkey") or item.get("eval_run_id") or len(by_key))
        by_key[key] = item
    return list(by_key.values())


def _is_correct(item: dict) -> bool:
    if _result_status(item) != "SUCCESS":
        return False
    score = _as_float(item.get("score"))
    return score is not None and score == 1


def _cell_score(results: object) -> float | None:
    items = _validator_items(results)
    scores: list[float] = []
    for item in items:
        score = _as_float(item.get("score"))
        if score is not None:
            scores.append(score)
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def _cell_kind(results: object) -> str:
    items = _validator_items(results)
    if not items:
        return "nodata"
    done = [
        item
        for item in items
        if _result_status(item) in {"SUCCESS", "FAILED", "FAIL", "TIMED_OUT", "TIMEOUT"}
    ]
    if not done:
        return "nodata"
    correct = sum(1 for item in done if _is_correct(item))
    answered = sum(1 for item in done if _result_status(item) in {"SUCCESS", "FAILED", "FAIL"})
    if correct == len(done):
        return "correct2"
    if correct > 0:
        return "correct1"
    if answered > 0:
        return "wrong"
    return "timeout"


def _filter_results(results: object, allowed_runs: set[str] | None) -> list[dict]:
    items = [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []
    if allowed_runs is None:
        return items
    kept: list[dict] = []
    for item in items:
        run_id = item.get("eval_run_id")
        if not run_id or str(run_id) in allowed_runs:
            kept.append(item)
    return kept


def _cells_for(
    problems: object,
    race_id: str,
    allowed_runs: set[str] | None = None,
) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {"product": [], "shop": [], "voucher": []}
    if not isinstance(problems, list):
        return buckets
    for item in problems:
        if not isinstance(item, dict) or str(item.get("race_id") or "") != race_id:
            continue
        phase = str(item.get("phase") or "").upper()
        if phase and phase not in {"RACE", "RACING"}:
            continue
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        category = str(item.get("category") or meta.get("category") or "").strip().lower()
        if category not in buckets:
            continue
        problem_id = item.get("problem_id") or meta.get("problem_id") or item.get("id")
        results = _filter_results(item.get("validator_results"), allowed_runs)
        buckets[category].append(
            {
                "kind": _cell_kind(results),
                "score": _cell_score(results),
                "problem_id": str(problem_id) if problem_id else None,
            }
        )
    for category, rows in buckets.items():
        del rows[30:]
        for index, row in enumerate(rows, start=1):
            row["n"] = index
    return buckets


def _generated_items(entry: object) -> list[dict]:
    if not isinstance(entry, dict):
        return []
    items = entry.get("items")
    if isinstance(items, dict):
        items = items.get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _tf_family_sums(items: list[dict]) -> dict[str, float] | None:
    """Per-family mean paid reward (0-1), matching oroagents.com family cards."""
    totals = {key: 0.0 for key in store.TF_KEYS}
    seen = {key: False for key in store.TF_KEYS}
    for item in items:
        raw_family = str(item.get("family") or "").strip()
        key = store.FAMILY_TO_TF.get(raw_family) or store.FAMILY_TO_TF.get(raw_family.lower())
        if not key:
            continue
        reward = _as_float(item.get("paid_reward"))
        if reward is None:
            reward = _as_float(item.get("score"))
        if reward is None and str(item.get("verdict_status") or "") == "passed":
            reward = 1.0
        if reward is None:
            continue
        totals[key] += reward
        seen[key] = True
    if not any(seen.values()):
        return None
    denom = float(store.TF_TASKS_PER_FAMILY)
    return {
        key: round(totals[key] / denom, 4) if seen[key] else None
        for key in store.TF_KEYS
    }


def _tf_cells_by_race(
    data: object,
    runs_by_race: dict[str, set[str]] | None,
) -> dict[str, dict[str, list[dict]]]:
    results = data.get("generated_results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return {}
    run_to_race: dict[str, str] = {}
    for race_id, run_ids in (runs_by_race or {}).items():
        for run_id in run_ids:
            run_to_race[str(run_id)] = str(race_id)
    by_race: dict[str, list[dict[str, float | None]]] = {}
    for entry in results:
        if not isinstance(entry, dict):
            continue
        ident = entry.get("identity") if isinstance(entry.get("identity"), dict) else {}
        run_id = str(ident.get("eval_run_id") or "")
        race_id = run_to_race.get(run_id)
        if not race_id:
            continue
        sums = _tf_family_sums(_generated_items(entry))
        if sums:
            by_race.setdefault(race_id, []).append(sums)
    out: dict[str, dict[str, list[dict]]] = {}
    for race_id, runs in by_race.items():
        cells: dict[str, list[dict]] = {}
        for key in store.TF_KEYS:
            values = [run[key] for run in runs if run.get(key) is not None]
            if not values:
                cells[key] = []
                continue
            avg = round(sum(float(value) for value in values) / len(values), 4)
            cells[key] = [{"n": 1, "kind": "score", "score": avg}]
        out[race_id] = cells
    return out


def _fetch_status(version_id: str) -> dict:
    cached = _status.get(version_id)
    if cached and cached.get("code") == "public":
        return cached
    data = {}
    for attempt in range(4):
        try:
            data = _fetch_json(f"{ORO_BASE}/agent-versions/{version_id}/status", timeout=12)
            if data:
                break
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(8 * (attempt + 1))
                continue
            break
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            time.sleep(0.4 * (attempt + 1))
    if not data:
        return cached or {"code": "private", "submitted_at": None}
    release = str(data.get("release_state") or "").strip().upper()
    available = data.get("code_available_at") or data.get("released_at")
    public = release == "RELEASED"
    if not public and isinstance(available, str) and available:
        try:
            parsed = datetime.fromisoformat(available.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            public = parsed <= datetime.now(timezone.utc)
        except ValueError:
            public = False
    row = {
        "code": "public" if public else "private",
        "submitted_at": _utc_iso(data.get("submitted_at")),
    }
    if not public and cached and cached.get("code") == "public":
        row = cached
    with _lock:
        _status[version_id] = row
    store.save_agent_status(version_id, row["code"], row.get("submitted_at"))
    return row


def _download_agent_bytes(version_id: str, limit: int = 1_200_000) -> bytes | None:
    for attempt in range(4):
        try:
            request = urllib.request.Request(
                f"{ORO_BASE}/artifacts/download-url",
                data=json.dumps({"artifact_type": "AGENT_CODE", "agent_version_id": version_id}).encode(),
                method="POST",
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))
            url = payload.get("download_url") if isinstance(payload, dict) else None
            if not url:
                time.sleep(0.4 * (attempt + 1))
                continue
            file_req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(file_req, timeout=25) as response:
                return response.read(limit)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(8 * (attempt + 1))
                continue
            if exc.code in {403, 404}:
                return None
            time.sleep(0.4 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
            time.sleep(0.4 * (attempt + 1))
    return None


def _decode_agent_files(raw: bytes) -> list[dict]:
    files: list[dict] = []
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = [
                    name
                    for name in archive.namelist()
                    if name.endswith(".py") and "__MACOSX" not in name and not name.endswith("/")
                ]
                if not names:
                    names = [
                        name
                        for name in archive.namelist()
                        if not name.endswith("/") and "__MACOSX" not in name
                    ]
                for name in names:
                    text = archive.read(name).decode("utf-8", errors="replace")
                    files.append({"name": name.rsplit("/", 1)[-1], "text": text})
        except zipfile.BadZipFile:
            return []
        files.sort(key=lambda item: len(item["text"]), reverse=True)
        return files
    text = raw.decode("utf-8", errors="replace")
    return [{"name": "agent.py", "text": text}] if text else []


def get_agent_code(version_id: str) -> dict:
    version_id = str(version_id or "").strip()
    empty = {"agent_version_id": version_id, "files": []}
    if not version_id:
        return empty
    cached = _code.get(version_id)
    if cached and cached.get("files"):
        return cached
    raw = _download_agent_bytes(version_id, limit=4_000_000)
    files = _decode_agent_files(raw) if raw else []
    row = {"agent_version_id": version_id, "files": files}
    if files:
        with _lock:
            _code[version_id] = row
    return row


def _count_source_lines(raw: bytes) -> int | None:
    if raw[:2] == b"PK":
        total = 0
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = [
                    name
                    for name in archive.namelist()
                    if name.endswith(".py") and "__MACOSX" not in name and not name.endswith("/")
                ]
                if not names:
                    names = [
                        name
                        for name in archive.namelist()
                        if not name.endswith("/") and "__MACOSX" not in name
                    ]
                for name in names:
                    text = archive.read(name).decode("utf-8", errors="ignore")
                    total += len(text.splitlines())
        except zipfile.BadZipFile:
            return None
        return total or None
    text = raw.decode("utf-8", errors="ignore")
    return len(text.splitlines()) or None


def _fetch_lines(version_id: str, is_public: bool) -> int | None:
    cached = _lines.get(version_id)
    if cached is not None:
        return cached
    if not is_public:
        return None
    _status_map, stored_lines, _cells, _counts, _overflow = store.load_agents([version_id])
    stored = stored_lines.get(version_id)
    if stored is not None:
        with _lock:
            _lines[version_id] = stored
        return stored
    raw = _download_agent_bytes(version_id, limit=4_000_000)
    lines = _count_source_lines(raw) if raw else None
    if lines is not None:
        with _lock:
            _lines[version_id] = lines
        store.save_agent_lines(version_id, lines)
    return lines


def _empty_cells() -> dict[str, list[dict]]:
    return {
        "product": [],
        "shop": [],
        "voucher": [],
        **{key: [] for key in store.TF_KEYS},
    }


def _has_race_cells(cells: object) -> bool:
    if not isinstance(cells, dict):
        return False
    return any(cells.get(key) for key in ("product", "shop", "voucher", *store.TF_KEYS))


def _remember_race_number(race_id: object, number: object) -> None:
    rid = str(race_id or "")
    try:
        value = int(number)
    except (TypeError, ValueError):
        return
    if rid:
        _race_number_by_id[rid] = value


def _problem_race_number(item: dict) -> object:
    number = item.get("race_number")
    if number is not None:
        return number
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return meta.get("race_number")


def _ensure_history_numbers() -> None:
    global _history_numbers_loaded
    if _history_numbers_loaded:
        return
    _history_numbers_loaded = True
    try:
        for race_id, summary in store.load_all_race_summaries().items():
            _remember_race_number(race_id, summary.get("race_number"))
        offset = 0
        while offset < 300:
            history = _fetch_json(f"{ORO_BASE}/races/history?limit=100&offset={offset}", timeout=20)
            batch = history.get("races") if isinstance(history, dict) else None
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if isinstance(item, dict):
                    _remember_race_number(item.get("race_id"), item.get("race_number"))
            offset += len(batch)
            total = history.get("total")
            if isinstance(total, int) and offset >= total:
                break
            if len(batch) < 100:
                break
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        _history_numbers_loaded = False


def _runs_by_race(version_id: str) -> dict[str, set[str]]:
    payload = {}
    for attempt in range(4):
        try:
            payload = _fetch_any(f"{ORO_BASE}/agent-versions/{version_id}/runs", timeout=20)
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(8 * (attempt + 1))
                continue
            if exc.code in {403, 500, 502, 503} and attempt < 3:
                time.sleep(0.5 * (attempt + 1))
                continue
            return {}
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            time.sleep(0.4 * (attempt + 1))
    runs = payload if isinstance(payload, list) else []
    if isinstance(payload, dict):
        for key in ("runs", "eval_runs", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                runs = value
                break
    by_race: dict[str, set[str]] = {}
    for run in runs:
        if not isinstance(run, dict) or run.get("invalidated_at"):
            continue
        status = str(run.get("status") or "").upper().replace(" ", "_")
        if status not in {"SUCCESS", "RUNNING", "CLAIMED"}:
            continue
        race_id = str(run.get("race_id") or "")
        run_id = run.get("eval_run_id")
        if race_id and run_id:
            by_race.setdefault(race_id, set()).add(str(run_id))
    return by_race


def _overflow_from_problems(
    problems: list,
    runs_by_race: dict[str, set[str]] | None = None,
) -> tuple[dict[str, dict], list[int], int]:
    raced_ids: list[str] = []
    for item in problems:
        if not isinstance(item, dict) or not item.get("race_id"):
            continue
        rid = str(item.get("race_id"))
        _remember_race_number(rid, _problem_race_number(item))
        phase = str(item.get("phase") or "").upper()
        if phase not in {"RACE", "RACING"}:
            continue
        if rid not in raced_ids:
            raced_ids.append(rid)
    for rid in runs_by_race or {}:
        if rid and rid not in raced_ids:
            raced_ids.append(rid)
    raced: dict[str, dict] = {}
    allowed = runs_by_race or {}
    for rid in raced_ids:
        cells = _cells_for(problems, rid, allowed.get(rid))
        if _has_race_cells(cells):
            raced[rid] = cells
    if raced_ids and any(rid not in _race_number_by_id for rid in raced_ids):
        _ensure_history_numbers()
    numbers = sorted({_race_number_by_id[rid] for rid in raced_ids if rid in _race_number_by_id})
    return raced, numbers, len(raced_ids)


def _lineage_race_numbers(version_id: object, through: object = None) -> list[int]:
    key = str(version_id or "").strip()
    if not key:
        return []
    numbers = store.load_lineage_races().get(key) or []
    limit = _race_int(through)
    if limit is None:
        return list(numbers)
    return [number for number in numbers if number <= limit]


def _apply_overflow_races(
    row: dict,
    extra: object = None,
    *,
    through: object = None,
) -> None:
    numbers = set(_lineage_race_numbers(row.get("agent_version_id")))
    current = _race_int(through)
    if current is not None:
        numbers.add(current)
    ordered = sorted(numbers)
    races = _merge_overflow_points(row.get("races"), extra)
    races = _merge_overflow_points(races, ordered)
    row["races"] = [
        point
        for point in races
        if _race_int(point.get("race_number")) in numbers
    ]
    row["race_count"] = len(ordered) or None


def _best_race_count(*values: object) -> int | None:
    best = 0
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > best:
            best = value
        elif isinstance(value, list) and len(value) > best:
            best = len(value)
    return best or None


def _merge_overflow_points(points: object, numbers: object) -> list[dict]:
    by_number: dict[int, dict] = {}
    if isinstance(points, list):
        for item in points:
            if not isinstance(item, dict) or item.get("race_number") is None:
                continue
            try:
                number = int(item["race_number"])
            except (TypeError, ValueError):
                continue
            by_number[number] = {**item, "race_number": number}
    if isinstance(numbers, list):
        for item in numbers:
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            by_number.setdefault(number, {"race_number": number})
    return [by_number[number] for number in sorted(by_number)]


def _race_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _overlay_standings_scores(rows: list[dict], race_number: object) -> None:
    current = _race_int(race_number)
    if current is None or not rows:
        return
    try:
        stored = store.load_current_standings() or {}
    except Exception:
        return
    if _race_int(stored.get("race_number")) != current:
        return
    by_id = {
        str(item.get("agent_version_id") or ""): item
        for item in (stored.get("rows") or [])
        if isinstance(item, dict) and item.get("agent_version_id")
    }
    for row in rows:
        src = by_id.get(str(row.get("agent_version_id") or ""))
        if not src:
            continue
        if row.get("race_score") is None:
            row["race_score"] = _as_float(src.get("race_score"))
        if row.get("overall_score") is None:
            row["overall_score"] = _as_float(src.get("overall_score"))
        by_race: dict[int, dict] = {}
        for point in row.get("races") or []:
            if not isinstance(point, dict):
                continue
            number = _race_int(point.get("race_number"))
            if number is not None:
                by_race[number] = {**point, "race_number": number}
        for point in src.get("previous") or []:
            if not isinstance(point, dict):
                continue
            number = _race_int(point.get("race_number"))
            if number is None:
                continue
            dest = by_race.setdefault(number, {"race_number": number})
            score = _as_float(point.get("score"))
            if dest.get("score") is None and score is not None:
                dest["score"] = score
        if by_race:
            row["races"] = [by_race[number] for number in sorted(by_race)]


def _first_score(*values: object) -> float | None:
    for value in values:
        score = _as_float(value)
        if score is not None:
            return score
    return None


def _races_with_scores(
    row: dict,
    index: dict[int, dict],
    current_number: object,
    cells: dict[str, dict] | None = None,
    id_by_number: dict[int, str] | None = None,
) -> list[dict]:
    version_id = str(row.get("agent_version_id") or "")
    lineage_key = store._lineage_index_key(row.get("agent_name"), row.get("miner_hotkey"))
    by_number: dict[int, dict] = {}
    for point in row.get("races") or []:
        if not isinstance(point, dict):
            continue
        number = _race_int(point.get("race_number"))
        if number is None:
            continue
        by_number[number] = point
    current = _race_int(current_number)
    if current is not None:
        by_number.setdefault(current, {"race_number": current})
    version_cells = (cells or {}).get(version_id) or {}
    rows = []
    for number in sorted(by_number):
        point = by_number[number]
        pack = index.get(number) or {}
        agent = dict((pack.get("by_lineage") or {}).get(lineage_key) or {})
        by_id = dict((pack.get("by_id") or {}).get(version_id) or {})
        for key, value in by_id.items():
            if value is not None:
                agent[key] = value
        avg = pack.get("avg") or {}
        race_id = (id_by_number or {}).get(number) or ""
        psv = version_cells.get(race_id) or {}
        if current == number:
            agent["o_score"] = _first_score(agent.get("o_score"), row.get("overall_score"))
            agent["r_score"] = _first_score(agent.get("r_score"), row.get("race_score"))
            agent["p_score"] = _first_score(agent.get("p_score"), row.get("product"))
            agent["s_score"] = _first_score(agent.get("s_score"), row.get("shop"))
            agent["v_score"] = _first_score(agent.get("v_score"), row.get("voucher"))
            for key in store.TF_KEYS:
                agent[f"{key}_score"] = _first_score(agent.get(f"{key}_score"), row.get(key))
            if agent.get("rank") is None:
                agent["rank"] = row.get("rank")
        o_score = _first_score(agent.get("o_score"), point.get("o_score"), point.get("overall_score"))
        r_score = _first_score(
            agent.get("r_score"),
            point.get("r_score"),
            point.get("score"),
            point.get("raw_score"),
        )
        p_score = _first_score(
            agent.get("p_score"),
            point.get("p_score"),
            point.get("product"),
            _first_psv(psv.get("product")),
        )
        s_score = _first_score(
            agent.get("s_score"),
            point.get("s_score"),
            point.get("shop"),
            _first_psv(psv.get("shop")),
        )
        v_score = _first_score(
            agent.get("v_score"),
            point.get("v_score"),
            point.get("voucher"),
            _first_psv(psv.get("voucher")),
        )
        tf_scores = {
            key: _first_score(
                agent.get(f"{key}_score"),
                point.get(f"{key}_score"),
                point.get(key),
                _first_tf(psv.get(key)),
            )
            for key in store.TF_KEYS
        }
        rows.append(
            {
                "race_number": number,
                "o_score": o_score,
                "o_mid": _first_score(avg.get("o_mid"), avg.get("o_avg")),
                "r_score": r_score,
                "r_mid": _first_score(avg.get("r_mid"), avg.get("r_avg")),
                "anchor": _first_score(avg.get("anchor")),
                "p_score": p_score,
                "p_mid": _first_score(avg.get("p_mid"), avg.get("p_avg")),
                "s_score": s_score,
                "s_mid": _first_score(avg.get("s_mid"), avg.get("s_avg")),
                "v_score": v_score,
                "v_mid": _first_score(avg.get("v_mid"), avg.get("v_avg")),
                **{f"{key}_score": tf_scores[key] for key in store.TF_KEYS},
                **{
                    f"{key}_mid": _first_score(avg.get(f"{key}_mid"), avg.get(f"{key}_avg"))
                    for key in store.TF_KEYS
                },
                "rank": agent.get("rank") if agent.get("rank") is not None else point.get("rank"),
                "o_rank": agent.get("o_rank")
                if agent.get("o_rank") is not None
                else store.metric_rank_for_score(pack, "o_score", "o_rank", o_score),
                "r_rank": agent.get("r_rank")
                if agent.get("r_rank") is not None
                else store.metric_rank_for_score(pack, "r_score", "r_rank", r_score),
                "p_rank": agent.get("p_rank")
                if agent.get("p_rank") is not None
                else store.metric_rank_for_score(pack, "p_score", "p_rank", p_score),
                "s_rank": agent.get("s_rank")
                if agent.get("s_rank") is not None
                else store.metric_rank_for_score(pack, "s_score", "s_rank", s_score),
                "v_rank": agent.get("v_rank")
                if agent.get("v_rank") is not None
                else store.metric_rank_for_score(pack, "v_score", "v_rank", v_score),
                **{
                    f"{key}_rank": agent.get(f"{key}_rank")
                    if agent.get(f"{key}_rank") is not None
                    else store.metric_rank_for_score(pack, f"{key}_score", f"{key}_rank", tf_scores[key])
                    for key in store.TF_KEYS
                },
            }
        )
    return rows


def _fetch_cells(version_id: str, race_id: str, force: bool = False) -> dict[str, list[dict]]:
    key = (version_id, race_id)
    cached = _cells.get(version_id, {}).get(race_id)
    if not force and key in _fetched_cells and cached is not None:
        return cached
    data = {}
    for attempt in range(4):
        try:
            data = _fetch_json(f"{ORO_BASE}/agent-versions/{version_id}/problems", timeout=25)
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(8 * (attempt + 1))
                continue
            if exc.code in {403, 500, 502, 503} and attempt < 3:
                time.sleep(0.5 * (attempt + 1))
                continue
            return cached or _empty_cells()
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            time.sleep(0.4 * (attempt + 1))
    if not isinstance(data, dict):
        return cached or _empty_cells()
    problems = data.get("problems")
    if not isinstance(problems, list):
        problems = []
    runs_by_race = _runs_by_race(version_id)
    raced, numbers, overflow_count = _overflow_from_problems(problems, runs_by_race)
    for rid, tf_cells in _tf_cells_by_race(data, runs_by_race).items():
        dest = raced.setdefault(rid, _empty_cells())
        dest.update(tf_cells)
    result = raced.get(race_id) or _empty_cells()
    with _lock:
        bucket = _cells.setdefault(version_id, {})
        bucket.update(raced)
        if race_id not in bucket:
            bucket[race_id] = result
        _race_counts[version_id] = overflow_count
        _overflow_numbers[version_id] = numbers
        for rid in raced:
            _fetched_cells.add((version_id, rid))
        _fetched_cells.add((version_id, race_id))
    store.save_agent_cells(
        version_id,
        raced or {race_id: result},
        overflow_count,
        numbers,
    )
    return result


def _missing_psv(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, list) and not value:
        return True
    return False


def _row_needs_psv(row: dict) -> bool:
    has_psv = not (
        _missing_psv(row.get("product"))
        or _missing_psv(row.get("shop"))
        or _missing_psv(row.get("voucher"))
    )
    has_tf = not any(_missing_psv(row.get(key)) for key in store.TF_KEYS)
    return not (has_psv or has_tf)


def _write_psv(row: dict, cells: dict) -> None:
    scored = _with_psv_scores(row, cells)
    row["product"] = scored.get("product")
    row["shop"] = scored.get("shop")
    row["voucher"] = scored.get("voucher")
    for key in store.TF_KEYS:
        if scored.get(key) is not None:
            row[key] = scored.get(key)


def _load_oro_psv(rows: list[dict], race_id: str, force: bool = False) -> None:
    pending = [
        str(row.get("agent_version_id") or "")
        for row in rows
        if row.get("agent_version_id") and (force or _row_needs_psv(row))
    ]
    pending = list(dict.fromkeys(pending))
    if not pending:
        return
    by_id = {
        str(row.get("agent_version_id") or ""): row
        for row in rows
        if row.get("agent_version_id")
    }

    def _one(version_id: str) -> tuple[str, dict]:
        return version_id, _fetch_cells(version_id, race_id, force=force)

    with ThreadPoolExecutor(max_workers=min(6, len(pending))) as pool:
        futures = [pool.submit(_one, version_id) for version_id in pending]
        for future in as_completed(futures):
            try:
                version_id, cells = future.result()
            except Exception:
                continue
            row = by_id.get(version_id)
            if row is not None:
                _write_psv(row, cells)


def _load_public_lines(version_ids: list[str], status_by_id: dict[str, dict]) -> dict[str, int]:
    need: list[str] = []
    seen: set[str] = set()
    for version_id in version_ids:
        if not version_id or version_id in seen:
            continue
        seen.add(version_id)
        code = (_status.get(version_id) or status_by_id.get(version_id) or {}).get("code")
        if code != "public":
            continue
        if _lines.get(version_id) is not None:
            continue
        need.append(version_id)
    if need:
        with ThreadPoolExecutor(max_workers=min(6, len(need))) as pool:
            list(pool.map(lambda version_id: _fetch_lines(version_id, True), need))
    return {
        version_id: lines
        for version_id, lines in _lines.items()
        if lines is not None
    }


def _load_code_status(version_ids: list[str]) -> dict[str, dict]:
    unique: list[str] = []
    seen: set[str] = set()
    for version_id in version_ids:
        if not version_id or version_id in seen:
            continue
        seen.add(version_id)
        unique.append(version_id)
    stored_status, _stored_lines, _stored_cells, _stored_counts, _overflow = store.load_agents(unique)
    for version_id, agent in stored_status.items():
        if agent.get("submitted_at") and version_id not in _status:
            with _lock:
                _status.setdefault(version_id, agent)
    need = [
        version_id
        for version_id in unique
        if not (_status.get(version_id) or stored_status.get(version_id) or {}).get("submitted_at")
    ]
    if need:
        with ThreadPoolExecutor(max_workers=min(6, len(need))) as pool:
            list(pool.map(_fetch_status, need))
    return {version_id: _status.get(version_id) or {} for version_id in unique}


def _load_cells(version_ids: list[str], race_id: str) -> None:
    pending = [
        (version_id, race_id)
        for version_id in version_ids
        if version_id and (version_id, race_id) not in _fetched_cells
    ]
    if not pending:
        return
    with ThreadPoolExecutor(max_workers=min(12, len(pending))) as pool:
        list(pool.map(lambda item: _fetch_cells(item[0], item[1]), pending))


def _enrich_one(args: tuple[str, str]) -> None:
    version_id, race_id = args
    status = _fetch_status(version_id)
    _fetch_lines(version_id, status.get("code") == "public")
    _fetch_cells(version_id, race_id)


def _enrich(race_id: str, version_ids: list[str]) -> None:
    try:
        need_status = [
            version_id
            for version_id in version_ids
            if version_id and version_id not in _status
        ]
        if need_status:
            with ThreadPoolExecutor(max_workers=min(6, len(need_status))) as pool:
                list(pool.map(_fetch_status, need_status))
        pending = [
            (version_id, race_id)
            for version_id in version_ids
            if version_id
            and (
                (
                    _status.get(version_id, {}).get("code") == "public"
                    and _lines.get(version_id) is None
                )
                or (version_id, race_id) not in _fetched_cells
            )
        ]
        if pending:
            with ThreadPoolExecutor(max_workers=min(6, len(pending))) as pool:
                list(pool.map(_enrich_one, pending))
        stored = store.load_race_table(race_id)
        payload = None
        stamp = time.monotonic()
        with _lock:
            cached = _cache.get(race_id)
            if cached:
                stamp, payload = cached
        if not payload:
            payload = stored
        if payload and payload.get("rows"):
            extras = []
            for row in payload.get("rows") or []:
                extras.append(_attach_extras(row, race_id))
            payload = {**payload, "rows": extras, "updated_at": datetime.now(timezone.utc).isoformat()}
            with _lock:
                _cache[race_id] = (stamp, payload)
            store.save_race_table(payload, True)
    finally:
        with _lock:
            _enriching.discard(race_id)


def _start_enrich(race_id: str, version_ids: list[str]) -> None:
    with _lock:
        if race_id in _enriching:
            return
        _enriching.add(race_id)
    threading.Thread(target=_enrich, args=(race_id, version_ids), daemon=True).start()


def _overflow_race_count(window: object, points: list[dict] | None = None) -> int:
    if isinstance(window, list):
        raced = []
        for item in window:
            if not isinstance(item, dict) or item.get("race_number") is None:
                continue
            if item.get("is_seed"):
                continue
            raced.append(item)
        if raced:
            return len(raced)
    if points:
        return len(points)
    return 0


def _window_points(window: object, score_key: str) -> list[dict]:
    points = []
    if not isinstance(window, list):
        return points
    for item in window:
        if not isinstance(item, dict):
            continue
        number = item.get("race_number")
        if score_key == "rank":
            rank = item.get("rank")
            try:
                score = 1.0 / float(rank) if rank else None
            except (TypeError, ValueError):
                score = None
        else:
            score = _as_float(item.get(score_key))
        if number is None or score is None:
            continue
        points.append({"race_number": number, "score": score})
    points.sort(key=lambda row: row["race_number"])
    return points


def _group_label(hotkey: str, coldkey: str, keys: list[dict]) -> str:
    for item in keys:
        if item.get("ss58") in {hotkey, coldkey}:
            return item.get("nickname") or item.get("group") or ""
    return ""


def _psv_score(cells: object) -> float | None:
    return store._psv_cell_score(cells)


def _tf_score(cells: object) -> float | None:
    if isinstance(cells, bool):
        return None
    if isinstance(cells, (int, float)):
        return _normalize_tf_score(float(cells))
    if not isinstance(cells, list) or not cells:
        return None
    total = 0.0
    seen = False
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        score = _as_float(cell.get("score"))
        if score is None:
            continue
        seen = True
        total += score
    if not seen:
        return None
    return _normalize_tf_score(total)


def _normalize_tf_score(score: float | None) -> float | None:
    """TF family cards are 0-1 means; legacy cells stored sum-of-rewards (~0-15)."""
    if score is None:
        return None
    value = float(score)
    if value > 1.0001:
        value = value / float(store.TF_TASKS_PER_FAMILY)
    return round(value, 4)


def _first_tf(*values: object) -> float | None:
    for value in values:
        if isinstance(value, (int, float)):
            return _normalize_tf_score(float(value))
        score = _tf_score(value)
        if score is not None:
            return score
    return None


def _first_psv(*values: object) -> float | None:
    for value in values:
        if isinstance(value, (int, float)):
            return float(value)
        score = _psv_score(value)
        if score is not None:
            return score
    return None


def _psv_cell_list(cells: object) -> list[dict]:
    by_n: dict[int, dict] = {}
    if isinstance(cells, list):
        for index, cell in enumerate(cells, start=1):
            if not isinstance(cell, dict):
                continue
            try:
                number = int(cell["n"]) if cell.get("n") is not None else index
            except (TypeError, ValueError):
                number = index
            if number < 1:
                continue
            entry = {
                "n": number,
                "kind": str(cell.get("kind") or "nodata"),
            }
            score = _as_float(cell.get("score"))
            if score is not None:
                entry["score"] = score
            by_n[number] = entry
    if not by_n:
        return []
    last = max(30, max(by_n))
    return [by_n.get(number, {"n": number, "kind": "nodata"}) for number in range(1, last + 1)]


def _with_psv_scores(row: dict, cells: dict | None = None) -> dict:
    extra = cells if isinstance(cells, dict) else {}
    item = {
        **row,
        "product": _first_psv(extra.get("product"), row.get("product")),
        "shop": _first_psv(extra.get("shop"), row.get("shop")),
        "voucher": _first_psv(extra.get("voucher"), row.get("voucher")),
        **{key: _first_tf(extra.get(key), row.get(key)) for key in store.TF_KEYS},
    }
    item.pop("product_cells", None)
    item.pop("shop_cells", None)
    item.pop("voucher_cells", None)
    return item


def _attach_extras(row: dict, race_id: str) -> dict:
    version_id = str(row.get("agent_version_id") or "")
    status = _status.get(version_id) or {}
    cells = _cells.get(version_id, {}).get(race_id) or {}
    _apply_overflow_races(row)
    races = row.get("races") or []
    code = status.get("code") or row.get("code") or "private"
    lines = _lines.get(version_id)
    if lines is None:
        lines = row.get("lines")
    if code != "public":
        lines = None
    item = {
        **row,
        "code": code,
        "lines": lines,
        "submitted_at": _utc_iso(status.get("submitted_at") or row.get("submitted_at")),
        "product": _first_psv(cells.get("product"), row.get("product")),
        "shop": _first_psv(cells.get("shop"), row.get("shop")),
        "voucher": _first_psv(cells.get("voucher"), row.get("voucher")),
        **{key: _first_tf(cells.get(key), row.get(key)) for key in store.TF_KEYS},
        "races": races,
        "race_count": row.get("race_count"),
    }
    item.pop("product_cells", None)
    item.pop("shop_cells", None)
    item.pop("voucher_cells", None)
    return item


def apply_code_meta(rows: list[dict]) -> None:
    version_ids = [
        str(row.get("agent_version_id") or "")
        for row in rows
        if isinstance(row, dict) and row.get("agent_version_id")
    ]
    status = _load_code_status(version_ids)
    fetched_lines = _load_public_lines(version_ids, status)
    for row in rows:
        if not isinstance(row, dict):
            continue
        version_id = str(row.get("agent_version_id") or "")
        agent = status.get(version_id) or {}
        if agent.get("code"):
            row["code"] = agent["code"]
        if row.get("code") == "public":
            row["lines"] = (
                fetched_lines.get(version_id)
                or _lines.get(version_id)
                or row.get("lines")
            )
        else:
            row["lines"] = None
        row["submitted_at"] = _utc_iso(agent.get("submitted_at")) or row.get("submitted_at")


def apply_public_lines(rows: list[dict]) -> None:
    version_ids = [
        str(row.get("agent_version_id") or "")
        for row in rows
        if isinstance(row, dict) and row.get("agent_version_id")
    ]
    status_by_id = {
        str(row.get("agent_version_id") or ""): {"code": row.get("code") or "private"}
        for row in rows
        if isinstance(row, dict) and row.get("agent_version_id")
    }
    fetched = _load_public_lines(version_ids, status_by_id)
    for row in rows:
        if not isinstance(row, dict):
            continue
        version_id = str(row.get("agent_version_id") or "")
        if (row.get("code") or status_by_id.get(version_id, {}).get("code")) != "public":
            row["lines"] = None
            continue
        lines = fetched.get(version_id)
        if lines is None:
            lines = _lines.get(version_id)
        if lines is None:
            lines = row.get("lines")
        if lines is not None:
            row["lines"] = lines


def apply_psv_scores(
    rows: list[dict],
    race_id: str,
    force: bool = False,
    *,
    top_fraction: float | None = None,
) -> None:
    race_id = str(race_id or "").strip()
    if not race_id or not rows:
        return
    target = store.top_agent_rows(rows, top_fraction) if top_fraction else rows
    _load_oro_psv(target, race_id, force=force)


def _fetch_race(race_id: str) -> dict:
    url = f"{ORO_BASE}/races/{race_id}"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return _fetch_json(url, timeout=25)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in {429, 500, 502, 503}:
                break
            time.sleep(0.5 * (attempt + 1))
    if last_error:
        raise last_error
    return {}


def _overall_by_version(wrap: dict) -> dict[str, float]:
    qualifiers = wrap.get("qualifiers") if isinstance(wrap.get("qualifiers"), list) else []
    by_id: dict[str, float] = {}
    for item in qualifiers:
        if not isinstance(item, dict):
            continue
        version_id = str(item.get("agent_version_id") or "")
        score = _as_float(item.get("weighted_score"))
        if version_id and score is not None:
            by_id[version_id] = score
    return by_id


def _fill_overall_scores(rows: list[dict], by_id: dict[str, float]) -> bool:
    changed = False
    for row in rows:
        if row.get("overall_score") is not None:
            continue
        score = by_id.get(str(row.get("agent_version_id") or ""))
        if score is None:
            continue
        row["overall_score"] = score
        changed = True
    return changed


def _ensure_stored_overall(stored: dict) -> dict:
    rows = [row for row in stored.get("rows") or [] if isinstance(row, dict)]
    if not rows or all(row.get("overall_score") is not None for row in rows):
        return stored
    race_id = str(stored.get("race_id") or stored.get("_id") or "")
    try:
        wrap = _fetch_race(race_id)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return stored
    if not _fill_overall_scores(rows, _overall_by_version(wrap)):
        return stored
    stored["rows"] = rows
    store.save_race_table(
        {
            "race_id": race_id,
            "race_number": stored.get("race_number"),
            "rows": rows,
        },
        bool(stored.get("enriched")),
    )
    return stored


_SCORED_STATUS = {
    "RACE_COMPLETE",
    "COMPLETED",
    "FINISHED",
    "CLOSED",
    "LIVE_RANKING",
    "RACE_RUNNING",
}


def _rows_missing_race_scores(rows: list) -> bool:
    items = [row for row in rows if isinstance(row, dict)]
    if not items:
        return True
    return not any(_as_float(row.get("race_score")) is not None for row in items)


def _rows_missing_overall_scores(rows: list) -> bool:
    items = [row for row in rows if isinstance(row, dict)]
    if not items:
        return True
    return not any(_as_float(row.get("overall_score")) is not None for row in items)


def _table_needs_score_refresh(stored: dict, status: str) -> bool:
    """Stale tables collected before scoring finished keep null race scores."""
    rows = [row for row in (stored.get("rows") or []) if isinstance(row, dict)]
    if not rows:
        return True
    if status not in _SCORED_STATUS:
        return False
    return _rows_missing_race_scores(rows)


def get_race_table(race_id: str) -> dict:
    race_id = str(race_id or "").strip()
    if not race_id:
        return _empty(race_id)
    stored = store.load_race_table(race_id) or {}
    summary = store.load_race_summary(race_id) or {}
    status = str(summary.get("status") or stored.get("status") or "").upper()
    has_rows = bool(stored.get("rows"))
    if has_rows and not _table_needs_score_refresh(stored, status):
        return _table_from_store(stored)
    # Re-fetch when the table is missing or was saved before race/overall scores existed.
    with _collect_lock(race_id):
        payload = _collect_race_table(race_id, start_enrich=has_rows)
    if payload.get("rows"):
        fresh_rows = payload.get("rows") or []
        if not has_rows or not _rows_missing_race_scores(fresh_rows):
            return payload
        if not _rows_missing_overall_scores(fresh_rows):
            return payload
    if has_rows:
        return _table_from_store(stored)
    return _empty(race_id)


def ingest_race_wrap(race_id: str, wrap: dict, *, start_enrich: bool = True) -> dict:
    return _collect_race_table(race_id, wrap=wrap, start_enrich=start_enrich)


def collect_race_tables(race_ids: list[str]) -> None:
    ids: list[str] = []
    seen: set[str] = set()
    for race_id in race_ids:
        rid = str(race_id or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        ids.append(rid)
    if not ids:
        return

    def _one(rid: str) -> None:
        with _collect_lock(rid):
            _collect_race_table(rid, start_enrich=False)

    with ThreadPoolExecutor(max_workers=min(8, len(ids))) as pool:
        list(pool.map(_one, ids))


def _collect_race_table(
    race_id: str,
    wrap: dict | None = None,
    *,
    start_enrich: bool = True,
) -> dict:
    payload = _empty(race_id)
    version_ids: list[str] = []
    try:
        if wrap is None:
            wrap = _fetch_race(race_id)
        race = wrap.get("race") if isinstance(wrap.get("race"), dict) else {}
        qualifiers = wrap.get("qualifiers") if isinstance(wrap.get("qualifiers"), list) else []
        if not race and isinstance(wrap.get("race_id"), str):
            race = wrap
        cold_by_hot = {}
        try:
            cold_by_hot.update(store.load_hotkey_owners())
        except Exception:
            pass
        for item in peek_registered_uids().get("rows") or []:
            if not isinstance(item, dict):
                continue
            hot = str(item.get("hotkey") or "").strip()
            cold = str(item.get("coldkey") or "").strip()
            if hot and cold:
                cold_by_hot[hot] = cold
        ranked = [item for item in qualifiers if isinstance(item, dict)]
        ranked.sort(
            key=lambda item: (
                0 if item.get("race_rank") is not None else 1,
                int(item.get("race_rank") or 0),
                0 if _as_float(item.get("race_score")) is not None else 1,
                -(_as_float(item.get("race_score")) or 0),
                str(item.get("agent_name") or "").lower(),
            )
        )
        keys = store.list_keys()
        version_ids = [
            str(item.get("agent_version_id") or "")
            for item in ranked
            if item.get("agent_version_id")
        ]
        stored_status, stored_lines, stored_cells, stored_counts, stored_overflow = store.load_agents(version_ids)
        rows = []
        for index, item in enumerate(ranked, start=1):
            version_id = str(item.get("agent_version_id") or "")
            hotkey = str(item.get("miner_hotkey") or "")
            coldkey = cold_by_hot.get(hotkey, "")
            window = item.get("window")
            if isinstance(window, list):
                for entry in window:
                    if isinstance(entry, dict):
                        _remember_race_number(entry.get("race_id"), entry.get("race_number"))
            window_points = _window_points(window, "raw_score")
            race_points = _merge_overflow_points(window_points, stored_overflow.get(version_id) or [])
            try:
                race_rank = int(item.get("race_rank")) if item.get("race_rank") is not None else None
            except (TypeError, ValueError):
                race_rank = None
            rows.append(
                {
                    "agent_version_id": version_id,
                    "rank": race_rank,
                    "agent_name": item.get("agent_name") or "",
                    "version_number": item.get("version_number"),
                    "miner_hotkey": hotkey,
                    "coldkey": coldkey,
                    "code": "private",
                    "lines": None,
                    "overall_score": _as_float(item.get("weighted_score")),
                    "race_score": _as_float(item.get("race_score")),
                    "qualifying_score": _as_float(item.get("qualifying_score")),
                    "product": None,
                    "shop": None,
                    "voucher": None,
                    **{key: None for key in store.TF_KEYS},
                    "submitted_at": _utc_iso(
                        item.get("submitted_at")
                        or item.get("created_at")
                        or item.get("code_submitted_at")
                    ),
                    "races": race_points,
                    "o_trend": _window_points(window, "rank"),
                    "r_trend": window_points,
                    "race_count": None,
                    "group": _group_label(hotkey, coldkey, keys),
                    "eliminated": bool(item.get("eliminated_at") or item.get("is_discarded")),
                }
            )
        fetched_status: dict[str, dict] = {}
        fetched_lines: dict[str, int] = {}
        if start_enrich:
            fetched_status = _load_code_status(version_ids)
            fetched_lines = _load_public_lines(version_ids, fetched_status)
        prev_rows = {
            str(item.get("agent_version_id") or ""): item
            for item in ((store.load_race_table(race_id) or {}).get("rows") or [])
            if isinstance(item, dict)
        }
        for row in rows:
            version_id = str(row.get("agent_version_id") or "")
            agent = fetched_status.get(version_id) or stored_status.get(version_id) or {}
            if agent.get("code"):
                row["code"] = agent["code"]
            if row.get("code") == "public":
                row["lines"] = fetched_lines.get(version_id) or stored_lines.get(version_id)
            else:
                row["lines"] = None
            row["submitted_at"] = _utc_iso(agent.get("submitted_at")) or row.get("submitted_at")
            scored = _with_psv_scores(
                prev_rows.get(version_id) or {},
                (stored_cells.get(version_id) or {}).get(race_id) or {},
            )
            row["product"] = scored.get("product")
            row["shop"] = scored.get("shop")
            row["voucher"] = scored.get("voucher")
            for key in store.TF_KEYS:
                row[key] = scored.get(key)
            _apply_overflow_races(row, through=race.get("race_number"))
        _overlay_standings_scores(rows, race.get("race_number"))
        payload = {
            "race_id": race_id,
            "race_number": race.get("race_number"),
            "score_mode": store.score_mode_for(race),
            "total": len(rows),
            "rows": rows,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        with _lock:
            if race_id in _cache:
                return _cache[race_id][1]
        existing = store.load_race_table(race_id)
        if existing and existing.get("rows"):
            return existing
        return payload
    if not rows:
        existing = store.load_race_table(race_id)
        if existing and existing.get("rows"):
            return existing
        return payload
    store.save_race_table(payload, False)
    with _lock:
        _cache[race_id] = (time.monotonic(), payload)
    if start_enrich:
        _start_enrich(race_id, version_ids)
    return payload
