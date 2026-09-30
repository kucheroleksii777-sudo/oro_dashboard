from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from . import store
from .auto_sub import submit_agent_file
from .my_agents import get_my_agents, pin_agent_version
from .network import fetch_tao_usd, get_network_stats
from .neurons import get_registered_uids
from .oro import (
    _with_key_fields,
    get_current_oro,
    get_current_race_standings,
    get_races_info_progress,
    get_races_list,
    get_races_update_progress,
    start_update_races_info,
    update_race_database,
)
from .race_table import get_agent_code, get_race_table
from .registration import DEFAULT_SPAN, SPANS, get_registration_history

_STRIP_KEYS = (
    "product_cells",
    "shop_cells",
    "voucher_cells",
    "o_trend",
    "r_trend",
)


def _without_psv_cells(payload: dict) -> dict:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return payload
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            cleaned.append(row)
            continue
        item = dict(row)
        for key in _STRIP_KEYS:
            item.pop(key, None)
        cleaned.append(item)
    return {**payload, "rows": cleaned}


@api_view(["GET"])
def health(_request: Request) -> Response:
    return Response({"status": "ok"})


@api_view(["GET", "HEAD"])
def network(request: Request) -> Response:
    refresh = str(request.query_params.get("refresh") or "").lower() in {"1", "true", "yes"}
    return Response(get_network_stats(refresh=refresh), headers={"Cache-Control": "no-store"})


@api_view(["GET"])
def tao(request: Request) -> Response:
    refresh = str(request.query_params.get("refresh") or "").lower() in {"1", "true", "yes"}
    return Response({"tao_usd": fetch_tao_usd(refresh=refresh)}, headers={"Cache-Control": "no-store"})


@api_view(["GET"])
def registration(request: Request) -> Response:
    span = str(request.query_params.get("span") or DEFAULT_SPAN).upper()
    if span not in SPANS:
        span = DEFAULT_SPAN
    return Response(get_registration_history(span))


@api_view(["GET"])
def neurons(_request: Request) -> Response:
    return Response(get_registered_uids(refresh=True), headers={"Cache-Control": "no-store"})


@api_view(["GET"])
def current(_request: Request) -> Response:
    try:
        payload = get_current_oro()
    except Exception:
        payload = {
            "race_number": None,
            "race_status": None,
            "qualifying_threshold": None,
            "race_threshold": None,
            "updated_at": None,
        }
    return Response(payload)


@api_view(["GET", "HEAD"])
def race(_request: Request) -> Response:
    try:
        # Overview: always Mongo-first. Ignore ?refresh=1 (no live force rebuild).
        payload = _with_key_fields(get_current_race_standings())
    except Exception:
        payload = {
            "race_number": None,
            "race_status": None,
            "race_threshold": None,
            "qualifying_threshold": None,
            "total": 0,
            "rows": [],
            "updated_at": None,
        }
    return Response(payload, headers={"Cache-Control": "no-store"})


@api_view(["GET", "POST"])
def races(request: Request) -> Response:
    if request.method == "POST":
        return Response(start_update_races_info(), headers={"Cache-Control": "no-store"})
    return Response(_without_psv_cells(get_races_list()), headers={"Cache-Control": "no-store"})


@api_view(["POST", "GET"])
def updatedb(request: Request) -> Response:
    data = request.data if request.method == "POST" else {}
    race_id = str(
        (data or {}).get("race_id") or request.query_params.get("race_id") or ""
    ).strip()
    return Response(update_race_database(race_id), headers={"Cache-Control": "no-store"})


@api_view(["GET"])
def races_progress(_request: Request) -> Response:
    return Response(get_races_update_progress(), headers={"Cache-Control": "no-store"})


@api_view(["GET", "POST"])
def races_info(_request: Request) -> Response:
    if _request.method == "POST":
        return Response(start_update_races_info(), headers={"Cache-Control": "no-store"})
    return Response(get_races_info_progress(), headers={"Cache-Control": "no-store"})


@api_view(["GET"])
def race_table(_request: Request, race_id: str) -> Response:
    return Response(_without_psv_cells(get_race_table(race_id)))


@api_view(["GET"])
def agent_code(_request: Request, version_id: str) -> Response:
    return Response(get_agent_code(version_id))


@api_view(["GET"])
def my_agents(_request: Request) -> Response:
    return Response(get_my_agents())


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def pin_agent(request: Request) -> Response:
    data = request.data or {}
    version_id = str(data.get("agent_version_id") or "").strip()
    hotkey = str(data.get("miner_hotkey") or "").strip()
    if not version_id or not hotkey:
        return Response({"ok": False, "error": "missing agent_version_id or miner_hotkey"}, status=400)
    result = pin_agent_version(version_id, hotkey)
    if not result.get("ok"):
        return Response(result, status=int(result.get("status") or 400))
    return Response(result)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def auto_sub_submit(request: Request) -> Response:
    hotkey = str(request.data.get("hotkey") or "").strip()
    agent_name = str(request.data.get("agent_name") or "").strip()
    uploaded = request.FILES.get("file")
    if not hotkey:
        return Response(
            {
                "ok": False,
                "status": "FAIL",
                "submitted_at": None,
                "next_allowed_at": None,
                "reason": "wallet-not-found",
            },
            status=400,
        )
    if uploaded is None:
        return Response(
            {
                "ok": False,
                "status": "FAIL",
                "submitted_at": None,
                "next_allowed_at": None,
                "reason": "invalid-file",
            },
            status=400,
        )
    result = submit_agent_file(hotkey, agent_name, uploaded.name, uploaded.read())
    return Response(result, status=200 if result.get("ok") else 400)


@api_view(["GET"])
def site(_request: Request) -> Response:
    return Response(
        {
            "title": "ORO dashboard",
            "brand": "ORO",
            "docs_url": "https://oroagents.com/docs",
            "tabs": [
                {"id": "home", "label": "Overview", "path": "/"},
                {"id": "agents", "label": "My Agents", "path": "/agents"},
                {"id": "overall", "label": "Overall", "path": "/overall"},
                {"id": "auto-sub", "label": "Auto-Sub", "path": "/auto-sub"},
                {"id": "reg", "label": "Reg", "path": "/reg"},
                {"id": "keys", "label": "Keys", "path": "/keys"},
                {"id": "docs", "label": "Docs", "path": "/docs"},
            ],
        }
    )


KEY_COLORS = (
    "#4ea1ff",
    "#3ecf8e",
    "#e89b25",
    "#f5d76e",
    "#e85d75",
    "#b57bff",
    "#2ec4d6",
    "#ff7eb6",
    "#9ad1ff",
    "#7ee081",
    "#ff9f68",
    "#c9a0dc",
)


def _next_key_color(used: object) -> str:
    taken = {str(item).strip().lower() for item in used if item}
    for color in KEY_COLORS:
        if color not in taken:
            return color
    hue = (len(taken) * 47) % 360
    sat = 0.68
    light = 0.58
    a = sat * min(light, 1 - light)

    def channel(n: float) -> str:
        k = (n + hue / 30) % 12
        value = light - a * max(min(k - 3, 9 - k, 1), -1)
        return f"{round(255 * value):02x}"

    return f"#{channel(0)}{channel(8)}{channel(4)}"


def _key_color(value: object, fallback: str = "#4ea1ff") -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in text[1:]):
        return text.lower()
    return fallback


def _unique_key_color(value: object, used: object) -> str:
    taken = {str(item).strip().lower() for item in used if item}
    color = _key_color(value, "")
    if color and color not in taken:
        return color
    return _next_key_color(taken)


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def keys(request: Request) -> Response:
    if request.method == "GET":
        return Response({"rows": store.list_keys()})

    data = request.data or {}
    ss58 = str(data.get("ss58") or "").strip()
    kind = str(data.get("kind") or store.KIND_COLD).strip().lower()
    group = str(data.get("group") or store.GROUP_OTHER).strip().lower()
    nickname = str(data.get("nickname") or "").strip()
    color = _unique_key_color(data.get("color"), store.key_colors())
    if kind not in {store.KIND_COLD, store.KIND_HOT}:
        kind = store.KIND_COLD
    if group not in {store.GROUP_MINE, store.GROUP_OTHER}:
        group = store.GROUP_OTHER
    if len(ss58) < 40 or len(ss58) > 64:
        return Response({"error": "invalid key"}, status=400)
    item, created = store.create_key(ss58, kind, group, nickname, color)
    return Response(item, status=201 if created else 200)


@api_view(["DELETE", "PATCH"])
@authentication_classes([])
@permission_classes([AllowAny])
def key_detail(request: Request, key_id: int) -> Response:
    item = store.get_key(key_id)
    if item is None:
        return Response({"error": "not found"}, status=404)
    if request.method == "DELETE":
        store.delete_key(key_id)
        return Response({"ok": True})

    data = request.data or {}
    if str(data.get("raise") or "").lower() in {"1", "true", "yes"} or data.get("raise") is True:
        updated = store.raise_key(key_id)
        return Response(updated or item)

    ss58 = str(data.get("ss58") or item["ss58"]).strip()
    kind = str(data.get("kind") or item["kind"]).strip().lower()
    nickname = str(data.get("nickname") if "nickname" in data else item["nickname"]).strip()
    color = _unique_key_color(
        data.get("color") if "color" in data else item["color"],
        store.key_colors(key_id),
    )
    if kind not in {store.KIND_COLD, store.KIND_HOT}:
        kind = item["kind"]
    if len(ss58) < 40 or len(ss58) > 64:
        return Response({"error": "invalid key"}, status=400)
    if store.ss58_taken(ss58, key_id):
        return Response({"error": "duplicate key"}, status=400)
    updated = store.update_key(key_id, ss58, kind, nickname, color)
    if updated is None:
        return Response({"error": "not found"}, status=404)
    return Response(updated)
