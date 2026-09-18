from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.database import get_engine
from app.errors import ApiError

router = APIRouter(prefix="/api/v1/health", tags=["Health"])


@router.get("")
def liveness():
    """The process is running. Used by load balancers. No authentication."""
    return {"status": "ok"}


@router.get("/ready")
def readiness(engine=Depends(get_engine)):
    """The API can reach the database. Returns 503 TEMPORARY_FAILURE if it cannot."""
    try:
        with engine.connect() as db:
            db.execute(text("SELECT 1"))
    except Exception as error:
        raise ApiError(503, "TEMPORARY_FAILURE", "The database is not reachable.") from error
    return {"status": "ready"}
