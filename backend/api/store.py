import math
from datetime import datetime, timezone

from pymongo import ReturnDocument, UpdateOne

from .mongo import ensure_indexes, get_db

KIND_COLD = "cold"
KIND_HOT = "hot"
GROUP_MINE = "mine"
GROUP_OTHER = "other"
SETTLED_STATUS = {"COMPLETED", "FINISHED", "CLOSED"}
OLD_SHOPPING_SUITE = 3
TF_FAMILIES = (
    ("tf1", "intent_decomposition"),
    ("tf2", "retrieval_recall"),
    ("tf3", "constraint_satisfaction"),
    ("tf4", "preference_reasoning"),
    ("tf5", "ranking"),
    ("tf6", "recovery"),
    ("tf7", "justification"),
)
TF_KEYS = tuple(key for key, _fam in TF_FAMILIES)
TF_MID_KEYS = tuple(f"{key}_mid" for key in TF_KEYS)
TF_SCORE_KEYS = tuple(f"{key}_score" for key in TF_KEYS)
TF_RANK_KEYS = tuple(f"{key}_rank" for key in TF_KEYS)
FAMILY_TO_TF = {family: key for key, family in TF_FAMILIES}
# Aliases seen in older / alternate ORO payloads.
FAMILY_TO_TF.update(
    {
        "preference": "tf4",
        "intent": "tf1",
        "retrieval": "tf2",
        "constraint": "tf3",
        "recall": "tf2",
    }
)
# Typical race pack size per family; used to normalize legacy sum-of-rewards cells.
TF_TASKS_PER_FAMILY = 15
SCORE_PACK_KEYS = (
    "o_score",
    "r_score",
    "p_score",
    "s_score",
    "v_score",
    *TF_SCORE_KEYS,
    "rank",
    "o_rank",
    "r_rank",
    "p_rank",
    "s_rank",
    "v_rank",
    *TF_RANK_KEYS,
)


def _suite_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_tf_race(item: dict | None) -> bool:
    row = item if isinstance(item, dict) else {}
    if str(row.get("score_mode") or "").lower() == "tf":
        return True
    suite = _suite_int(row.get("suite_id"))
    if suite is not None:
        return suite != OLD_SHOPPING_SUITE
    try:
        number = int(row.get("race_number"))
    except (TypeError, ValueError):
        number = None
    completed = str(row.get("completed_at") or row.get("race_completed_at") or "")
    return number is not None and number < 100 and completed >= "2026-09-10"


def score_mode_for(item: dict | None) -> str:
    return "tf" if is_tf_race(item) else "psv"
_initialized = False
_settled: dict[str, bool] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clear_race_data() -> None:
    db = get_db()
    for name in (
        "races",
        "race_tables",
        "agents",
        "agent_cells",
        "standings",
        "race_thresholds",
        "live_race_scores",
    ):
        try:
            db[name].delete_many({})
        except Exception:
            continue


def initialize_database() -> None:
    global _initialized
    if _initialized:
        return
    ensure_indexes()
    _initialized = True


def _db():
    ensure_indexes()
    return get_db()


def _next_id(name: str) -> int:
    doc = get_db().counters.find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


def _set_counter(name: str, value: int) -> None:
    get_db().counters.update_one({"_id": name}, {"$set": {"seq": value}}, upsert=True)


def _iso(value: object) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[no-any-return]
    text = str(value or "").strip()
    return text.replace(" ", "T", 1) if text else _now()


def _key_sort(doc: dict) -> int | None:
    try:
        if doc.get("sort") is None:
            return None
        return int(doc["sort"])
    except (TypeError, ValueError):
        return None


def _key_row(doc: dict) -> dict:
    return {
        "id": int(doc["_id"]),
        "ss58": doc.get("ss58") or "",
        "kind": doc.get("kind") or KIND_COLD,
        "group": doc.get("group") or GROUP_MINE,
        "nickname": doc.get("nickname") or "",
        "color": doc.get("color") or "#4ea1ff",
        "created_at": doc.get("created_at") or "",
        "sort": _key_sort(doc) if _key_sort(doc) is not None else 0,
    }


def _ensure_key_sorts(group: str) -> None:
    try:
        docs = list(_db().keys.find({"group": group}))
    except Exception:
        return
    if not docs or all(_key_sort(doc) is not None for doc in docs):
        return
    docs.sort(key=lambda doc: (doc.get("created_at") or "", int(doc.get("_id") or 0)))
    for index, doc in enumerate(docs):
        try:
            _db().keys.update_one({"_id": doc["_id"]}, {"$set": {"sort": index}})
        except Exception:
            return


def _next_key_sort(group: str) -> int:
    _ensure_key_sorts(group)
    try:
        last = _db().keys.find({"group": group}).sort("sort", -1).limit(1)
        for doc in last:
            value = _key_sort(doc)
            return (value if value is not None else -1) + 1
    except Exception:
        return 0
    return 0


def migrate_mine_keys_to_other() -> None:
    try:
        mine = list(_db().keys.find({"group": GROUP_MINE}))
    except Exception:
        return
    if not mine:
        return
    mine.sort(
        key=lambda doc: (
            _key_sort(doc) if _key_sort(doc) is not None else 10**9,
            doc.get("created_at") or "",
            int(doc.get("_id") or 0),
        )
    )
    try:
        others = list(_db().keys.find({"group": GROUP_OTHER}))
    except Exception:
        others = []
    shift = len(mine)
    for doc in others:
        current = _key_sort(doc)
        next_sort = (current if current is not None else 0) + shift
        try:
            _db().keys.update_one({"_id": doc["_id"]}, {"$set": {"sort": next_sort}})
        except Exception:
            return
    for index, doc in enumerate(mine):
        try:
            _db().keys.update_one(
                {"_id": doc["_id"]},
                {"$set": {"group": GROUP_OTHER, "sort": index}},
            )
        except Exception:
            return


def list_keys() -> list[dict]:
    _ensure_key_sorts(GROUP_MINE)
    _ensure_key_sorts(GROUP_OTHER)
    try:
        docs = list(_db().keys.find())
    except Exception:
        return []
    docs.sort(
        key=lambda doc: (
            0 if doc.get("group") == GROUP_MINE else 1,
            _key_sort(doc) if _key_sort(doc) is not None else 10**9,
            doc.get("created_at") or "",
            int(doc.get("_id") or 0),
        )
    )
    return [_key_row(doc) for doc in docs]


def load_my_hotkeys() -> dict[str, dict]:
    try:
        docs = list(_db().my_hotkeys.find())
    except Exception:
        return {}
    rows: dict[str, dict] = {}
    for doc in docs:
        ss58 = str(doc.get("_id") or doc.get("ss58") or "")
        if not ss58:
            continue
        rows[ss58] = {
            "ss58": ss58,
            "coldkey": str(doc.get("coldkey") or ""),
            "name": str(doc.get("name") or ""),
            "uid": doc.get("uid"),
            "was_registered": bool(doc.get("was_registered") or doc.get("uid") is not None),
        }
    return rows


def load_hotkey_owners() -> dict[str, str]:
    try:
        docs = list(_db().hotkey_owners.find())
    except Exception:
        return {}
    owners: dict[str, str] = {}
    for doc in docs:
        hot = str(doc.get("_id") or doc.get("hotkey") or "")
        cold = str(doc.get("coldkey") or "")
        if hot and cold:
            owners[hot] = cold
    return owners


def save_hotkey_owners(pairs: dict[str, str]) -> None:
    ops = []
    for hot, cold in pairs.items():
        hotkey = str(hot or "").strip()
        coldkey = str(cold or "").strip()
        if not hotkey or not coldkey:
            continue
        ops.append(
            UpdateOne(
                {"_id": hotkey},
                {"$set": {"hotkey": hotkey, "coldkey": coldkey}},
                upsert=True,
            )
        )
    if not ops:
        return
    try:
        _db().hotkey_owners.bulk_write(ops, ordered=False)
    except Exception:
        return


def save_my_hotkeys(items: list[dict]) -> None:
    ops = []
    for item in items:
        ss58 = str(item.get("ss58") or "")
        if not ss58:
            continue
        fields = {"ss58": ss58}
        if item.get("coldkey"):
            fields["coldkey"] = str(item.get("coldkey") or "")
        if item.get("name"):
            fields["name"] = str(item.get("name") or "")
        if item.get("uid") is not None:
            try:
                fields["uid"] = int(item["uid"])
            except (TypeError, ValueError):
                pass
            fields["was_registered"] = True
        elif item.get("was_registered"):
            fields["was_registered"] = True
        ops.append(UpdateOne({"_id": ss58}, {"$set": fields}, upsert=True))
    if not ops:
        return
    try:
        _db().my_hotkeys.bulk_write(ops, ordered=False)
    except Exception:
        return


def delete_my_hotkeys(ss58s: list[str] | set[str]) -> None:
    ids = [str(ss58) for ss58 in ss58s if ss58]
    if not ids:
        return
    try:
        _db().my_hotkeys.delete_many({"_id": {"$in": ids}})
    except Exception:
        return


def load_my_agent_snapshot() -> list[dict]:
    try:
        doc = _db().my_agent_snapshot.find_one({"_id": "mine"})
    except Exception:
        return []
    rows = doc.get("rows") if isinstance(doc, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def save_my_agent_snapshot(rows: list[dict]) -> None:
    try:
        _db().my_agent_snapshot.replace_one(
            {"_id": "mine"},
            {"_id": "mine", "rows": rows, "updated_at": _now()},
            upsert=True,
        )
    except Exception:
        return


def save_hotkey_cooldown(hotkey: str, ends_at: str) -> None:
    key = (hotkey or "").strip()
    when = (ends_at or "").strip()
    if not key or not when:
        return
    try:
        _db().hotkey_cooldowns.replace_one(
            {"_id": key},
            {"_id": key, "ends_at": when, "updated_at": _now()},
            upsert=True,
        )
    except Exception:
        return


def load_hotkey_cooldowns() -> dict[str, str]:
    try:
        docs = _db().hotkey_cooldowns.find()
    except Exception:
        return {}
    out: dict[str, str] = {}
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        key = str(doc.get("_id") or "").strip()
        when = str(doc.get("ends_at") or "").strip()
        if key and when:
            out[key] = when
    return out


def key_colors(exclude_id: int | None = None) -> list[str]:
    query = {} if exclude_id is None else {"_id": {"$ne": exclude_id}}
    try:
        return [str(doc.get("color") or "") for doc in _db().keys.find(query, {"color": 1})]
    except Exception:
        return []


def ss58_taken(ss58: str, exclude_id: int | None = None) -> bool:
    query: dict = {"ss58": ss58}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}
    try:
        return _db().keys.find_one(query) is not None
    except Exception:
        return False


def get_key(key_id: int) -> dict | None:
    try:
        doc = _db().keys.find_one({"_id": key_id})
    except Exception:
        return None
    return _key_row(doc) if doc else None


def create_key(ss58: str, kind: str, group: str, nickname: str, color: str) -> tuple[dict, bool]:
    db = _db()
    existing = db.keys.find_one({"ss58": ss58})
    if existing:
        return _key_row(existing), False
    doc = {
        "_id": _next_id("keys"),
        "ss58": ss58,
        "kind": kind,
        "group": group,
        "nickname": nickname,
        "color": color,
        "created_at": _now(),
        "sort": _next_key_sort(group),
    }
    db.keys.insert_one(doc)
    return _key_row(doc), True


def update_key(key_id: int, ss58: str, kind: str, nickname: str, color: str) -> dict | None:
    db = _db()
    result = db.keys.find_one_and_update(
        {"_id": key_id},
        {"$set": {"ss58": ss58, "kind": kind, "nickname": nickname, "color": color}},
        return_document=ReturnDocument.AFTER,
    )
    return _key_row(result) if result else None


def raise_key(key_id: int) -> dict | None:
    item = get_key(key_id)
    if item is None:
        return None
    group = item.get("group") or GROUP_MINE
    _ensure_key_sorts(group)
    try:
        docs = list(_db().keys.find({"group": group}))
    except Exception:
        return item
    docs.sort(
        key=lambda doc: (
            _key_sort(doc) if _key_sort(doc) is not None else 10**9,
            doc.get("created_at") or "",
            int(doc.get("_id") or 0),
        )
    )
    index = next((i for i, doc in enumerate(docs) if int(doc["_id"]) == key_id), -1)
    if index <= 0:
        return item
    above = docs[index - 1]
    current = docs[index]
    above_sort = _key_sort(above)
    current_sort = _key_sort(current)
    if above_sort is None:
        above_sort = index - 1
    if current_sort is None:
        current_sort = index
    try:
        _db().keys.update_one({"_id": above["_id"]}, {"$set": {"sort": current_sort}})
        _db().keys.update_one({"_id": current["_id"]}, {"$set": {"sort": above_sort}})
    except Exception:
        return item
    return get_key(key_id)


def delete_key(key_id: int) -> bool:
    try:
        result = _db().keys.delete_one({"_id": key_id})
    except Exception:
        return False
    return result.deleted_count > 0


def _score_values(rows: list, key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            value = row.get(key)
            if value is None:
                continue
            if isinstance(value, (list, dict)):
                score = _psv_cell_score(value)
                if score is None:
                    continue
                values.append(float(score))
                continue
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _top_slice(values: list[float], fraction: float) -> list[float]:
    ranked = sorted(values, reverse=True)
    count = max(1, math.ceil(len(ranked) * fraction))
    return ranked[:count]


def _mean_score(rows: list, key: str, fraction: float | None = None) -> float | None:
    values = _score_values(rows, key)
    if not values:
        return None
    if fraction is None:
        return round(sum(values) / len(values), 4)
    top = _top_slice(values, fraction)
    return round(sum(top) / len(top), 4)


def _median_values(values: list[float]) -> float | None:
    if not values:
        return None
    ranked = sorted(values)
    mid = len(ranked) // 2
    if len(ranked) % 2:
        return round(ranked[mid], 4)
    return round((ranked[mid - 1] + ranked[mid]) / 2, 4)


def _median_top_score(rows: list, key: str, fraction: float = 0.35) -> float | None:
    values = _score_values(rows, key)
    if not values:
        return None
    return _median_values(_top_slice(values, fraction))


def top_agent_rows(rows: object, fraction: float = 0.35) -> list[dict]:
    agents = [
        row
        for row in (rows or [])
        if isinstance(row, dict)
        and not row.get("eliminated")
        and not row.get("is_discarded")
    ]
    if not agents:
        agents = [row for row in (rows or []) if isinstance(row, dict)]
    if not agents:
        return []

    def sort_key(row: dict) -> tuple[int, float]:
        try:
            rank = int(row["rank"]) if row.get("rank") is not None else 10**9
        except (TypeError, ValueError):
            rank = 10**9
        try:
            score = float(row["race_score"]) if row.get("race_score") is not None else float("-inf")
        except (TypeError, ValueError):
            score = float("-inf")
        return (rank, -score)

    agents.sort(key=sort_key)
    count = max(1, math.ceil(len(agents) * fraction))
    return agents[:count]


def _mid_or_avg(row: dict, mid_key: str, avg_key: str):
    if row.get(mid_key) is not None:
        return row.get(mid_key)
    return row.get(avg_key)


def averages_from_rows(rows: object) -> dict:
    items = [row for row in rows or [] if isinstance(row, dict)]
    top = top_agent_rows(items)
    return {
        "overall_mid": _median_top_score(items, "overall_score"),
        "race_mid": _median_top_score(items, "race_score"),
        "p_mid": _median_values(_score_values(top, "product")),
        "s_mid": _median_values(_score_values(top, "shop")),
        "v_mid": _median_values(_score_values(top, "voucher")),
        **{f"{key}_mid": _median_values(_score_values(top, key)) for key in TF_KEYS},
    }


def _as_score(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _empty_score_pack() -> dict:
    return {key: None for key in SCORE_PACK_KEYS}


def _merge_score_pack(dest: dict, src: dict, *, replace: bool = False) -> dict:
    for key in SCORE_PACK_KEYS:
        if src.get(key) is None:
            continue
        if replace or dest.get(key) is None:
            dest[key] = src[key]
    if src.get("in_race"):
        dest["in_race"] = True
    return dest


def _assign_metric_ranks(out: dict[int, dict]) -> None:
    # o/r/p/s/v_rank = unique order by that score among agents in the same race.
    pairs = (
        ("o_score", "o_rank"),
        ("r_score", "r_rank"),
        ("p_score", "p_rank"),
        ("s_score", "s_rank"),
        ("v_score", "v_rank"),
        *zip(TF_SCORE_KEYS, TF_RANK_KEYS),
    )
    for pack in out.values():
        by_id = pack.get("by_id") or {}
        members = {
            version_id: agent
            for version_id, agent in by_id.items()
            if agent.get("in_race") or all(not item.get("in_race") for item in by_id.values())
        }
        for score_key, rank_key in pairs:
            scored = []
            for version_id, agent in members.items():
                score = _as_score(agent.get(score_key))
                if score is None:
                    continue
                scored.append((score, version_id))
            scored.sort(key=lambda item: (-item[0], item[1]))
            for index, (_score, version_id) in enumerate(scored, start=1):
                by_id[version_id][rank_key] = index


def metric_rank_for_score(pack: dict, score_key: str, rank_key: str, score: object) -> int | None:
    value = _as_score(score)
    if value is None:
        return None
    best = None
    for agent in (pack.get("by_id") or {}).values():
        if _as_score(agent.get(score_key)) != value:
            continue
        try:
            rank = int(agent.get(rank_key))
        except (TypeError, ValueError):
            continue
        if rank > 0 and (best is None or rank < best):
            best = rank
    return best


def _lineage_index_key(name: object, hotkey: object) -> str:
    return f"{str(name or '').strip()}\x1f{str(hotkey or '').strip()}"


def _index_pack(out: dict[int, dict], number: int) -> dict:
    pack = out.get(number)
    if pack is None:
        pack = {"avg": {}, "by_id": {}, "by_lineage": {}}
        out[number] = pack
    pack.setdefault("by_lineage", {})
    return pack


def _put_index_scores(
    out: dict[int, dict],
    number: int,
    version_id: str,
    scores: dict,
    *,
    replace: bool = False,
) -> None:
    if not version_id or not scores:
        return
    pack = _index_pack(out, number)
    dest = pack["by_id"].setdefault(version_id, _empty_score_pack())
    _merge_score_pack(dest, scores, replace=replace)


def _put_index_lineage(
    out: dict[int, dict],
    number: int,
    name: object,
    hotkey: object,
    scores: dict,
    *,
    replace: bool = False,
) -> None:
    key = _lineage_index_key(name, hotkey)
    if not key.strip("\x1f") or not scores:
        return
    pack = _index_pack(out, number)
    dest = pack["by_lineage"].setdefault(key, _empty_score_pack())
    _merge_score_pack(dest, scores, replace=replace)


def _load_cell_scores() -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    try:
        cursor = _db().agent_cells.find(
            {},
            {
                "race_id": 1,
                "agent_version_id": 1,
                "product": 1,
                "shop": 1,
                "voucher": 1,
                **{key: 1 for key in TF_KEYS},
            },
        )
        for item in cursor:
            race_id = str(item.get("race_id") or "")
            version_id = str(item.get("agent_version_id") or "")
            if not race_id or not version_id:
                continue
            out.setdefault(race_id, {})[version_id] = {
                "p_score": _psv_cell_score(item.get("product")),
                "s_score": _psv_cell_score(item.get("shop")),
                "v_score": _psv_cell_score(item.get("voucher")),
                **{f"{key}_score": _tf_cell_score(item.get(key)) for key in TF_KEYS},
            }
    except Exception:
        return {}
    return out


def load_race_score_index() -> dict[int, dict]:
    out: dict[int, dict] = {}
    cell_scores = _load_cell_scores()
    try:
        cursor = _db().race_tables.find(
            {},
            {
                "race_number": 1,
                "race_id": 1,
                "rows.agent_version_id": 1,
                "rows.agent_name": 1,
                "rows.miner_hotkey": 1,
                "rows.rank": 1,
                "rows.overall_score": 1,
                "rows.race_score": 1,
                "rows.product": 1,
                "rows.shop": 1,
                "rows.voucher": 1,
                **{f"rows.{key}": 1 for key in TF_KEYS},
                "rows.races": 1,
                "rows.previous": 1,
            },
        )
        for row in cursor:
            try:
                number = int(row.get("race_number"))
            except (TypeError, ValueError):
                continue
            race_id = str(row.get("race_id") or row.get("_id") or "")
            cells = cell_scores.get(race_id) or {}
            rows = [item for item in (row.get("rows") or []) if isinstance(item, dict)]
            avg_rows = []
            for item in rows:
                cell = cells.get(str(item.get("agent_version_id") or "")) or {}
                avg_rows.append(
                    {
                        **item,
                        "product": cell["p_score"] if cell.get("p_score") is not None else item.get("product"),
                        "shop": cell["s_score"] if cell.get("s_score") is not None else item.get("shop"),
                        "voucher": cell["v_score"] if cell.get("v_score") is not None else item.get("voucher"),
                        **{
                            key: cell.get(f"{key}_score")
                            if cell.get(f"{key}_score") is not None
                            else item.get(key)
                            for key in TF_KEYS
                        },
                    }
                )
            avgs = averages_from_rows(avg_rows)
            pack = _index_pack(out, number)
            for key, value in {
                "o_mid": avgs.get("overall_mid"),
                "r_mid": avgs.get("race_mid"),
                "p_mid": avgs.get("p_mid"),
                "s_mid": avgs.get("s_mid"),
                "v_mid": avgs.get("v_mid"),
                **{key: avgs.get(key) for key in TF_MID_KEYS},
            }.items():
                if pack["avg"].get(key) is None and value is not None:
                    pack["avg"][key] = value
            for item in rows:
                version_id = str(item.get("agent_version_id") or "")
                if not version_id:
                    continue
                cell = cells.get(version_id) or {}
                scores = {
                    "o_score": _as_score(item.get("overall_score")),
                    "r_score": _as_score(item.get("race_score")),
                    "p_score": cell.get("p_score")
                    if cell.get("p_score") is not None
                    else _as_score(item.get("product")),
                    "s_score": cell.get("s_score")
                    if cell.get("s_score") is not None
                    else _as_score(item.get("shop")),
                    "v_score": cell.get("v_score")
                    if cell.get("v_score") is not None
                    else _as_score(item.get("voucher")),
                    **{
                        f"{key}_score": cell.get(f"{key}_score")
                        if cell.get(f"{key}_score") is not None
                        else _as_score(item.get(key))
                        for key in TF_KEYS
                    },
                    "rank": item.get("rank"),
                    "in_race": True,
                }
                _put_index_scores(out, number, version_id, scores, replace=True)
                _put_index_lineage(
                    out,
                    number,
                    item.get("agent_name"),
                    item.get("miner_hotkey"),
                    scores,
                    replace=True,
                )
                for point in (*(item.get("races") or []), *(item.get("previous") or [])):
                    if not isinstance(point, dict):
                        continue
                    try:
                        point_n = int(point.get("race_number"))
                    except (TypeError, ValueError):
                        continue
                    point_scores = {
                        "o_score": _as_score(point.get("o_score") or point.get("overall_score")),
                        "r_score": _as_score(
                            point.get("r_score")
                            if point.get("r_score") is not None
                            else point.get("score")
                            if point.get("score") is not None
                            else point.get("raw_score")
                        ),
                        "p_score": _as_score(point.get("p_score") or point.get("product")),
                        "s_score": _as_score(point.get("s_score") or point.get("shop")),
                        "v_score": _as_score(point.get("v_score") or point.get("voucher")),
                        **{
                            f"{key}_score": _as_score(point.get(f"{key}_score") or point.get(key))
                            for key in TF_KEYS
                        },
                    }
                    _put_index_scores(out, point_n, version_id, point_scores)
                    _put_index_lineage(
                        out,
                        point_n,
                        item.get("agent_name"),
                        item.get("miner_hotkey"),
                        point_scores,
                    )
    except Exception:
        return out
    try:
        stored = load_current_standings() or {}
        try:
            current = int(stored.get("race_number"))
        except (TypeError, ValueError):
            current = None
        stand_rows = [item for item in (stored.get("rows") or []) if isinstance(item, dict)]
        if current is not None and stand_rows:
            avgs = averages_from_rows(
                [
                    {
                        "overall_score": item.get("overall_score"),
                        "race_score": item.get("race_score"),
                    "product": item.get("product"),
                    "shop": item.get("shop"),
                    "voucher": item.get("voucher"),
                    **{key: item.get(key) for key in TF_KEYS},
                }
                for item in stand_rows
                ]
            )
            pack = _index_pack(out, current)
            for key, value in {
                "o_mid": avgs.get("overall_mid"),
                "r_mid": avgs.get("race_mid"),
                "p_mid": avgs.get("p_mid"),
                "s_mid": avgs.get("s_mid"),
                "v_mid": avgs.get("v_mid"),
                **{key: avgs.get(key) for key in TF_MID_KEYS},
            }.items():
                if pack["avg"].get(key) is None and value is not None:
                    pack["avg"][key] = value
            stand_race_id = str(stored.get("race_id") or "")
            stand_cells = cell_scores.get(stand_race_id) or {}
            for item in stand_rows:
                version_id = str(item.get("agent_version_id") or "")
                if not version_id:
                    continue
                cell = stand_cells.get(version_id) or {}
                _put_index_scores(
                    out,
                    current,
                    version_id,
                    {
                        "o_score": _as_score(item.get("overall_score")),
                        "r_score": _as_score(item.get("race_score")),
                        "p_score": cell.get("p_score")
                        if cell.get("p_score") is not None
                        else _as_score(item.get("product")),
                        "s_score": cell.get("s_score")
                        if cell.get("s_score") is not None
                        else _as_score(item.get("shop")),
                        "v_score": cell.get("v_score")
                        if cell.get("v_score") is not None
                        else _as_score(item.get("voucher")),
                        **{
                            f"{key}_score": cell.get(f"{key}_score")
                            if cell.get(f"{key}_score") is not None
                            else _as_score(item.get(key))
                            for key in TF_KEYS
                        },
                        "in_race": True,
                    },
                    replace=True,
                )
                for point in item.get("previous") or []:
                    if not isinstance(point, dict):
                        continue
                    try:
                        point_n = int(point.get("race_number"))
                    except (TypeError, ValueError):
                        continue
                    _put_index_scores(
                        out,
                        point_n,
                        version_id,
                        {
                            "r_score": _as_score(point.get("score")),
                            "o_score": _as_score(point.get("o_score")),
                        },
                    )
    except Exception:
        pass
    for pack in out.values():
        by_id = pack.get("by_id") or {}
        avg = pack.setdefault("avg", {})
        if all(avg.get(key) is not None for key in ("o_mid", "r_mid", "p_mid", "s_mid", "v_mid", *TF_MID_KEYS)):
            continue
        filled = averages_from_rows(
            [
                {
                    "overall_score": item.get("o_score"),
                    "race_score": item.get("r_score"),
                    "product": item.get("p_score"),
                    "shop": item.get("s_score"),
                    "voucher": item.get("v_score"),
                    **{key: item.get(f"{key}_score") for key in TF_KEYS},
                }
                for item in by_id.values()
            ]
        )
        for key, src in (
            ("o_mid", "overall_mid"),
            ("r_mid", "race_mid"),
            ("p_mid", "p_mid"),
            ("s_mid", "s_mid"),
            ("v_mid", "v_mid"),
            *((key, key) for key in TF_MID_KEYS),
        ):
            if avg.get(key) is None and filled.get(src) is not None:
                avg[key] = filled[src]
    fields = load_race_anchors()
    for number, field in fields.items():
        if number in out:
            out[number].setdefault("avg", {})["anchor"] = field
    _assign_metric_ranks(out)
    return out


def _psv_cell_score(cells: object) -> float | None:
    if isinstance(cells, bool):
        return None
    if isinstance(cells, (int, float)):
        return float(cells)
    if not isinstance(cells, list) or not cells:
        return None
    total = 0.0
    seen = False
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        kind = str(cell.get("kind") or "")
        score = _as_score(cell.get("score"))
        if kind == "nodata" and score is None:
            continue
        seen = True
        if kind == "correct1":
            continue
        if kind == "correct2" or score == 1:
            total += 1.0
    return round(total, 1) if seen else None


def _tf_cell_score(cells: object) -> float | None:
    if isinstance(cells, bool):
        return None
    if isinstance(cells, (int, float)):
        return float(cells)
    if not isinstance(cells, list) or not cells:
        return None
    total = 0.0
    seen = False
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        score = _as_score(cell.get("score"))
        if score is None:
            continue
        seen = True
        total += score
    return round(total, 1) if seen else None


def load_psv_averages(race_ids: list[str] | None = None) -> dict[str, dict]:
    wanted = [rid for rid in (race_ids or []) if rid]
    query: dict = {}
    if race_ids is not None:
        if not wanted:
            return {}
        query = {"race_id": {"$in": wanted}}
    buckets: dict[str, list[dict]] = {}
    try:
        for row in _db().agent_cells.find(query, {"race_id": 1, "product": 1, "shop": 1, "voucher": 1}):
            race_id = str(row.get("race_id") or "")
            if not race_id:
                continue
            buckets.setdefault(race_id, []).append(
                {
                    "product": _psv_cell_score(row.get("product")),
                    "shop": _psv_cell_score(row.get("shop")),
                    "voucher": _psv_cell_score(row.get("voucher")),
                }
            )
    except Exception:
        return {}
    return {race_id: averages_from_rows(rows) for race_id, rows in buckets.items()}


def load_race_averages(race_ids: list[str] | None = None) -> dict[str, dict]:
    query = {"_id": {"$in": [rid for rid in (race_ids or []) if rid]}} if race_ids is not None else {}
    out: dict[str, dict] = {}
    try:
        cursor = _db().race_tables.find(
            query,
            {
                "rows.overall_score": 1,
                "rows.race_score": 1,
                "rows.product": 1,
                "rows.shop": 1,
                "rows.voucher": 1,
            },
        )
        for row in cursor:
            out[str(row.get("_id") or row.get("race_id") or "")] = averages_from_rows(
                row.get("rows") or []
            )
    except Exception:
        return out
    out.pop("", None)
    missing = [
        rid
        for rid in (race_ids or list(out))
        if rid
        and (
            not out.get(rid)
            or out[rid].get("p_mid") is None
            or out[rid].get("s_mid") is None
            or out[rid].get("v_mid") is None
        )
    ]
    if race_ids is None:
        missing = None
    cells = load_psv_averages(missing)
    for race_id, avgs in cells.items():
        dest = out.setdefault(race_id, {})
        for key in ("p_mid", "s_mid", "v_mid"):
            if dest.get(key) is None and avgs.get(key) is not None:
                dest[key] = avgs[key]
    still = [
        rid
        for rid in (missing if missing is not None else list(out))
        if rid
        and (
            not out.get(rid)
            or out[rid].get("p_mid") is None
            or out[rid].get("s_mid") is None
            or out[rid].get("v_mid") is None
        )
    ]
    if still:
        try:
            number_docs = list(
                _db().races.find({"_id": {"$in": still}}, {"race_number": 1})
            )
        except Exception:
            number_docs = []
        index = load_race_score_index()
        for doc in number_docs:
            race_id = str(doc.get("_id") or "")
            try:
                number = int(doc.get("race_number"))
            except (TypeError, ValueError):
                continue
            idx_avg = (index.get(number) or {}).get("avg") or {}
            dest = out.setdefault(race_id, {})
            for key in ("p_mid", "s_mid", "v_mid"):
                if dest.get(key) is None and idx_avg.get(key) is not None:
                    dest[key] = idx_avg[key]
    return out


def save_race_psv_averages(race_id: str, avgs: dict) -> None:
    race_id = str(race_id or "").strip()
    fields = {
        key: avgs[key]
        for key in ("p_mid", "s_mid", "v_mid", *TF_MID_KEYS)
        if avgs.get(key) is not None
    }
    if not race_id or not fields:
        return
    try:
        _db().races.update_one({"_id": race_id}, {"$set": fields})
    except Exception:
        return


def race_summary_row(row: dict) -> dict:
    return {
        "race_id": row.get("race_id") or row.get("_id"),
        "race_number": row.get("race_number"),
        "status": row.get("status") or None,
        "is_latest": False,
        "agent_count": row.get("agent_count") or 0,
        "completed_at": row.get("completed_at") or None,
        "overall_agent": row.get("overall_agent") or None,
        "overall_score": row.get("overall_score"),
        "race_agent": row.get("race_agent") or None,
        "race_score": row.get("race_score"),
        "race_threshold": row.get("race_threshold"),
        "qualifying_threshold": row.get("qualifying_threshold"),
        "overall_mid": _mid_or_avg(row, "overall_mid", "overall_avg"),
        "race_mid": _mid_or_avg(row, "race_mid", "race_avg"),
        "p_mid": _mid_or_avg(row, "p_mid", "p_avg"),
        "s_mid": _mid_or_avg(row, "s_mid", "s_avg"),
        "v_mid": _mid_or_avg(row, "v_mid", "v_avg"),
        "suite_id": row.get("suite_id"),
        "score_mode": score_mode_for(row),
        **{key: _mid_or_avg(row, key, key.replace("_mid", "_avg")) for key in TF_MID_KEYS},
    }


def load_all_race_summaries() -> dict[str, dict]:
    try:
        return {str(row["_id"]): race_summary_row(row) for row in _db().races.find()}
    except Exception:
        return {}


def load_race_summary(race_id: str) -> dict | None:
    try:
        row = _db().races.find_one({"_id": race_id})
    except Exception:
        return None
    return race_summary_row(row) if row else None


def save_race_info(summary: dict) -> None:
    race_id = str(summary.get("race_id") or "").strip()
    if not race_id:
        return
    try:
        doc = {
            "_id": race_id,
            "race_id": race_id,
            "race_number": summary.get("race_number"),
            "status": str(summary.get("status") or ""),
            "agent_count": int(summary.get("agent_count") or 0),
            "completed_at": summary.get("completed_at") or None,
            "overall_agent": summary.get("overall_agent") or None,
            "overall_score": summary.get("overall_score"),
            "race_agent": summary.get("race_agent") or None,
            "race_score": summary.get("race_score"),
            "race_threshold": summary.get("race_threshold"),
            "qualifying_threshold": summary.get("qualifying_threshold"),
            "overall_mid": summary.get("overall_mid"),
            "race_mid": summary.get("race_mid"),
            "p_mid": summary.get("p_mid"),
            "s_mid": summary.get("s_mid"),
            "v_mid": summary.get("v_mid"),
            "suite_id": summary.get("suite_id"),
            "score_mode": score_mode_for(summary),
            **{key: summary.get(key) for key in TF_MID_KEYS},
        }
        _db().races.replace_one({"_id": race_id}, doc, upsert=True)
        if doc["completed_at"] or str(doc["status"] or "").upper() in SETTLED_STATUS:
            _settled[race_id] = True
    except Exception:
        return


def save_race_summary(summary: dict) -> None:
    race_id = str(summary.get("race_id") or "").strip()
    if not race_id:
        return
    try:
        existing = _db().races.find_one({"_id": race_id}) or {}
        doc = {
            "_id": race_id,
            "race_id": race_id,
            "race_number": summary.get("race_number")
            if summary.get("race_number") is not None
            else existing.get("race_number"),
            "status": str(summary.get("status") or existing.get("status") or ""),
            "agent_count": int(summary.get("agent_count") or existing.get("agent_count") or 0),
            "completed_at": summary.get("completed_at") or existing.get("completed_at") or None,
            "overall_agent": summary.get("overall_agent")
            if summary.get("overall_agent") is not None
            else existing.get("overall_agent") or None,
            "overall_score": summary.get("overall_score")
            if summary.get("overall_score") is not None
            else existing.get("overall_score"),
            "race_agent": summary.get("race_agent")
            if summary.get("race_agent") is not None
            else existing.get("race_agent") or None,
            "race_score": summary.get("race_score")
            if summary.get("race_score") is not None
            else existing.get("race_score"),
            "race_threshold": summary.get("race_threshold")
            if summary.get("race_threshold") is not None
            else existing.get("race_threshold"),
            "qualifying_threshold": summary.get("qualifying_threshold")
            if summary.get("qualifying_threshold") is not None
            else existing.get("qualifying_threshold"),
            "overall_mid": summary.get("overall_mid")
            if summary.get("overall_mid") is not None
            else _mid_or_avg(existing, "overall_mid", "overall_avg"),
            "race_mid": summary.get("race_mid")
            if summary.get("race_mid") is not None
            else _mid_or_avg(existing, "race_mid", "race_avg"),
            "p_mid": summary.get("p_mid")
            if summary.get("p_mid") is not None
            else _mid_or_avg(existing, "p_mid", "p_avg"),
            "s_mid": summary.get("s_mid")
            if summary.get("s_mid") is not None
            else _mid_or_avg(existing, "s_mid", "s_avg"),
            "v_mid": summary.get("v_mid")
            if summary.get("v_mid") is not None
            else _mid_or_avg(existing, "v_mid", "v_avg"),
            "suite_id": summary.get("suite_id")
            if summary.get("suite_id") is not None
            else existing.get("suite_id"),
            "score_mode": score_mode_for(
                {
                    **existing,
                    **{
                        key: summary.get(key)
                        for key in ("suite_id", "score_mode", "race_number", "completed_at")
                        if summary.get(key) is not None
                    },
                }
            ),
            **{
                key: summary.get(key)
                if summary.get(key) is not None
                else _mid_or_avg(existing, key, key.replace("_mid", "_avg"))
                for key in TF_MID_KEYS
            },
        }
        _db().races.replace_one({"_id": race_id}, doc, upsert=True)
        if doc["completed_at"] or str(doc["status"] or "").upper() in SETTLED_STATUS:
            _settled[race_id] = True
    except Exception:
        return


def race_is_settled(race_id: str, race: dict | None = None) -> bool:
    if not race and race_id in _settled:
        return _settled[race_id]
    race = race if isinstance(race, dict) else {}
    status = str(race.get("status") or "").upper()
    completed = race.get("completed_at") or race.get("race_completed_at")
    if completed or status in SETTLED_STATUS:
        _settled[race_id] = True
        return True
    stored = load_race_summary(race_id)
    settled = bool(
        stored and (stored.get("completed_at") or str(stored.get("status") or "").upper() in SETTLED_STATUS)
    )
    _settled[race_id] = settled
    return settled


def load_current_standings() -> dict | None:
    try:
        row = _db().standings.find_one({"_id": "current"})
    except Exception:
        return None
    if not row or not row.get("rows"):
        return None
    return {
        "race_number": row.get("race_number"),
        "race_status": row.get("race_status"),
        "race_threshold": row.get("race_threshold"),
        "qualifying_threshold": row.get("qualifying_threshold"),
        "total": row.get("total") or len(row.get("rows") or []),
        "rows": list(row.get("rows") or []),
        "updated_at": row.get("updated_at"),
        "finished_race": row.get("finished_race") or None,
    }


def load_live_race_scores(race_id: str) -> dict[str, float]:
    if not race_id:
        return {}
    try:
        doc = _db().live_race_scores.find_one({"_id": race_id})
    except Exception:
        return {}
    scores = doc.get("scores") if isinstance(doc, dict) else None
    if not isinstance(scores, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in scores.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def save_live_race_scores(race_id: str, scores: dict[str, float]) -> None:
    if not race_id or not scores:
        return
    fields = {f"scores.{version_id}": score for version_id, score in scores.items() if version_id}
    if not fields:
        return
    try:
        _db().live_race_scores.update_one({"_id": race_id}, {"$set": fields}, upsert=True)
    except Exception:
        return


def save_current_standings(payload: dict) -> None:
    if not payload or not payload.get("rows"):
        return
    try:
        _db().standings.replace_one(
            {"_id": "current"},
            {
                "_id": "current",
                "race_number": payload.get("race_number"),
                "race_status": payload.get("race_status"),
                "race_threshold": payload.get("race_threshold"),
                "qualifying_threshold": payload.get("qualifying_threshold"),
                "total": payload.get("total") or len(payload.get("rows") or []),
                "rows": payload.get("rows") or [],
                "updated_at": payload.get("updated_at") or _now(),
                "finished_race": payload.get("finished_race") or None,
            },
            upsert=True,
        )
    except Exception:
        return


def load_race_tables_by_numbers(numbers: list[int]) -> dict[int, dict]:
    wanted = []
    for number in numbers:
        try:
            wanted.append(int(number))
        except (TypeError, ValueError):
            continue
    if not wanted:
        return {}
    out: dict[int, dict] = {}
    seen_at: dict[int, str] = {}
    try:
        # Suite resets reuse race_number. Prefer the newest table per number so
        # Overview WIN/Margin do not pick an older suite's scores.
        for row in _db().race_tables.find({"race_number": {"$in": wanted}}):
            try:
                number = int(row.get("race_number"))
            except (TypeError, ValueError):
                continue
            updated = str(row.get("updated_at") or "")
            if number in out and updated <= seen_at.get(number, ""):
                continue
            seen_at[number] = updated
            out[number] = {
                "race_id": row.get("race_id") or row.get("_id"),
                "race_number": number,
                "total": len(row.get("rows") or []),
                "rows": list(row.get("rows") or []),
                "enriched": bool(row.get("enriched")),
                "updated_at": row.get("updated_at"),
            }
    except Exception:
        return out
    return out


def load_race_table(race_id: str) -> dict | None:
    try:
        row = _db().race_tables.find_one({"_id": race_id})
    except Exception:
        return None
    if not row:
        return None
    return {
        "race_id": row.get("race_id") or race_id,
        "race_number": row.get("race_number"),
        "total": len(row.get("rows") or []),
        "rows": list(row.get("rows") or []),
        "enriched": bool(row.get("enriched")),
        "updated_at": row.get("updated_at"),
    }


_lineage_races: dict[str, list[int]] | None = None


def load_lineage_races() -> dict[str, list[int]]:
    global _lineage_races
    if _lineage_races is not None:
        return _lineage_races
    out: dict[str, set[int]] = {}
    try:
        for table in _db().race_tables.find({}, {"race_number": 1, "rows": 1}):
            try:
                number = int(table.get("race_number"))
            except (TypeError, ValueError):
                continue
            for row in table.get("rows") or []:
                if not isinstance(row, dict):
                    continue
                version_id = str(row.get("agent_version_id") or "").strip()
                if not version_id:
                    continue
                out.setdefault(version_id, set()).add(number)
    except Exception:
        return _lineage_races or {}
    _lineage_races = {key: sorted(values) for key, values in out.items()}
    return _lineage_races


def save_race_table(payload: dict, enriched: bool) -> None:
    race_id = str(payload.get("race_id") or "").strip()
    if not race_id:
        return
    global _lineage_races
    _lineage_races = None
    try:
        rows = []
        for row in payload.get("rows") or []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item.pop("product_cells", None)
            item.pop("shop_cells", None)
            item.pop("voucher_cells", None)
            rows.append(item)
        _db().race_tables.replace_one(
            {"_id": race_id},
            {
                "_id": race_id,
                "race_id": race_id,
                "race_number": payload.get("race_number"),
                "rows": rows,
                "enriched": enriched,
                "updated_at": _now(),
            },
            upsert=True,
        )
        avgs = averages_from_rows(rows)
        fields = {
            key: avgs[key]
            for key in ("overall_mid", "race_mid", "p_mid", "s_mid", "v_mid", *TF_MID_KEYS)
            if avgs.get(key) is not None
        }
        _db().races.update_one({"_id": race_id}, {"$set": fields}, upsert=False)
    except Exception:
        return


def _overflow_numbers(value: object) -> list[int]:
    numbers: list[int] = []
    if not isinstance(value, list):
        return numbers
    for item in value:
        try:
            numbers.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(set(numbers))


def load_agents(
    version_ids: list[str],
) -> tuple[
    dict[str, dict],
    dict[str, int],
    dict[str, dict[str, dict]],
    dict[str, int],
    dict[str, list[int]],
]:
    ids = [version_id for version_id in version_ids if version_id]
    if not ids:
        return {}, {}, {}, {}, {}
    status: dict[str, dict] = {}
    lines: dict[str, int] = {}
    counts: dict[str, int] = {}
    overflow: dict[str, list[int]] = {}
    cells: dict[str, dict[str, dict]] = {}
    try:
        db = _db()
        for row in db.agents.find({"_id": {"$in": ids}}):
            vid = str(row["_id"])
            status[vid] = {
                "code": row.get("code") or None,
                "submitted_at": row.get("submitted_at") or None,
            }
            if row.get("lines") is not None:
                lines[vid] = int(row["lines"])
            numbers = _overflow_numbers(row.get("overflow_races"))
            if numbers:
                overflow[vid] = numbers
                counts[vid] = max(counts.get(vid, 0), len(numbers))
            if row.get("race_count") is not None:
                counts[vid] = max(counts.get(vid, 0), int(row["race_count"]))
        for row in db.agent_cells.find({"agent_version_id": {"$in": ids}}):
            vid = str(row.get("agent_version_id") or "")
            race_id = str(row.get("race_id") or "")
            if not vid or not race_id:
                continue
            store = cells.setdefault(vid, {})
            store[race_id] = {
                "product": row.get("product") or [],
                "shop": row.get("shop") or [],
                "voucher": row.get("voucher") or [],
                **{key: row.get(key) or [] for key in TF_KEYS},
            }
    except Exception:
        return {}, {}, {}, {}, {}
    return status, lines, cells, counts, overflow


def save_agent_status(version_id: str, code: str, submitted_at: object) -> None:
    if not version_id:
        return
    try:
        fields = {"code": code or "private"}
        if submitted_at:
            fields["submitted_at"] = submitted_at
        _db().agents.update_one({"_id": version_id}, {"$set": fields}, upsert=True)
    except Exception:
        return


def save_agent_lines(version_id: str, lines: int) -> None:
    if not version_id or lines is None:
        return
    try:
        _db().agents.update_one({"_id": version_id}, {"$set": {"lines": lines}}, upsert=True)
    except Exception:
        return


def save_agent_cells(
    version_id: str,
    by_race: dict[str, dict],
    race_count: int,
    overflow_races: list[int] | None = None,
) -> None:
    if not version_id:
        return
    try:
        db = _db()
        ops = []
        for race_id, buckets in by_race.items():
            if not race_id:
                continue
            ops.append(
                UpdateOne(
                    {"agent_version_id": version_id, "race_id": str(race_id)},
                    {
                        "$set": {
                            "agent_version_id": version_id,
                            "race_id": str(race_id),
                            "product": buckets.get("product") or [],
                            "shop": buckets.get("shop") or [],
                            "voucher": buckets.get("voucher") or [],
                            **{key: buckets.get(key) or [] for key in TF_KEYS},
                        }
                    },
                    upsert=True,
                )
            )
        if ops:
            db.agent_cells.bulk_write(ops, ordered=False)
        existing = db.agents.find_one({"_id": version_id}) or {}
        prev_count = 0
        try:
            prev_count = int(existing.get("race_count") or 0)
        except (TypeError, ValueError):
            prev_count = 0
        merged = sorted(set(_overflow_numbers(existing.get("overflow_races"))) | set(overflow_races or []))
        fields: dict[str, object] = {
            "race_count": max(prev_count, int(race_count or 0), len(merged)),
        }
        if merged:
            fields["overflow_races"] = merged
        db.agents.update_one({"_id": version_id}, {"$set": fields}, upsert=True)
    except Exception:
        return


def save_race_thresholds(thresholds: dict[int, float]) -> None:
    if not thresholds:
        return
    try:
        ops = []
        for number, value in thresholds.items():
            try:
                key = int(number)
                threshold = float(value)
            except (TypeError, ValueError):
                continue
            ops.append(
                UpdateOne(
                    {"_id": key},
                    {"$set": {"threshold": threshold, "updated_at": _now()}},
                    upsert=True,
                )
            )
        if ops:
            _db().race_thresholds.bulk_write(ops, ordered=False)
    except Exception:
        return


def load_race_thresholds() -> dict[int, float]:
    try:
        out: dict[int, float] = {}
        for row in _db().race_thresholds.find():
            try:
                out[int(row["_id"])] = float(row["threshold"])
            except (TypeError, ValueError, KeyError):
                continue
        return out
    except Exception:
        return {}


def load_race_anchors() -> dict[int, float]:
    out = dict(load_race_thresholds())
    try:
        for row in _db().races.find({}, {"race_number": 1, "race_threshold": 1}):
            try:
                number = int(row.get("race_number"))
            except (TypeError, ValueError):
                continue
            field = _as_score(row.get("race_threshold"))
            if field is None:
                continue
            out[number] = field
    except Exception:
        pass
    return out
