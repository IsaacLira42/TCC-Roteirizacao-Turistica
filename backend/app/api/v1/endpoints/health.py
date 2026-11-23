from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/health")


@router.get("/")
def health():
    return {"status": "ok"}


@router.get("/live")
def live():
    return {"status": "ok"}


@router.get("/ready")
def ready():
    from sqlalchemy import text
    from app.core.database import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready", "db": "connected"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")