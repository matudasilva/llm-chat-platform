from fastapi import APIRouter

from app.infra.db import test_db_connection
from app.infra.redis_client import test_redis_connection

router = APIRouter(prefix="/health", tags=["ops"])


@router.get("/deps")
async def health_deps():
    await test_db_connection()
    await test_redis_connection()
    return {
        "postgres": "ok",
        "redis": "ok",
    }
