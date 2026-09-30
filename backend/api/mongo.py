import os
from functools import lru_cache

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

DEFAULT_URI = "mongodb://127.0.0.1:27017"
DEFAULT_DB = "oro_dashboard"

_indexes_ready = False


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    uri = os.environ.get("MONGO_URI", DEFAULT_URI)
    return MongoClient(uri, serverSelectionTimeoutMS=4000)


def get_db() -> Database:
    name = os.environ.get("MONGO_DB", DEFAULT_DB)
    return get_client()[name]


def ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    db = get_db()
    db.keys.create_index("ss58", unique=True)
    db.races.create_index([("race_number", ASCENDING)])
    db.race_tables.create_index("enriched")
    db.agents.create_index("code")
    db.agent_cells.create_index([("agent_version_id", ASCENDING), ("race_id", ASCENDING)], unique=True)
    _indexes_ready = True
