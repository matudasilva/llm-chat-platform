from fastapi import APIRouter

router = APIRouter(tags=["ops"])

# Day 5:
# Dependency-level health checks are intentionally deferred.
# /health/deps will be introduced in Day 6/7 once migrations/persistence are in place.
