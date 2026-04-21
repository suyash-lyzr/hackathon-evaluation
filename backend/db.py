import os
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from bson.errors import InvalidId

_client = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        db_url = os.getenv("DB_URL", "mongodb://localhost:27017")
        db_name = os.getenv("DB_NAME", "architect")
        _client = AsyncIOMotorClient(db_url)
        _db = _client[db_name]
    return _db


async def fetch_app(app_id: str) -> dict | None:
    """Fetch an app document by id. Accepts both ObjectId hex strings and raw string ids."""
    db = get_db()
    apps = db["apps"]

    app_id = (app_id or "").strip()
    if not app_id:
        return None

    try:
        oid = ObjectId(app_id)
        doc = await apps.find_one({"_id": oid})
        if doc:
            return doc
    except InvalidId:
        pass

    return await apps.find_one({"_id": app_id})
