from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.readiness_service import check_database_ready

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/ready")
def readiness(db: Session = Depends(get_db)):
    try:
        return check_database_ready(db.connection())
    except Exception:
        db.rollback()
        raise HTTPException(status_code=503, detail="Database schema is not ready; check migrations.") from None
