import httpx
from fastapi import APIRouter

from config import HARDCOVER_API_KEY
from db.mongo import ping_mongo
from models.health import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/livez")
async def liveness():
    """Lightweight pod probe; external provider health is checked separately."""
    return {"status": "ok"}


@router.get("/health", response_model=HealthResponse)
async def health():
    """Checks the status of all four external integrations. No auth required."""
    integrations: dict[str, str] = {}

    # HardCover API — minimal GraphQL query to confirm the service is reachable
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.hardcover.app/v1/graphql",
                headers={"Authorization": HARDCOVER_API_KEY, "Content-Type": "application/json"},
                json={"query": "{ __typename }"},
                timeout=5,
            )
        integrations["hardcover"] = "ok" if r.status_code == 200 else "degraded"
    except Exception:
        integrations["hardcover"] = "unavailable"

    # MongoDB
    integrations["mongodb"] = "ok" if await ping_mongo() else "unavailable"

    # Tavily
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.tavily.com/health", timeout=5)
        integrations["tavily"] = "ok" if r.status_code == 200 else "degraded"
    except Exception:
        integrations["tavily"] = "unavailable"

    # LangSmith
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.smith.langchain.com/health", timeout=5)
        integrations["langsmith"] = "ok" if r.status_code == 200 else "degraded"
    except Exception:
        integrations["langsmith"] = "unavailable"

    overall = "ok" if all(v == "ok" for v in integrations.values()) else "degraded"
    return HealthResponse(status=overall, integrations=integrations)
