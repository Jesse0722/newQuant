from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.exceptions import AppError, app_error_handler

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="量化交易系统", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppError, app_error_handler)

from app.routers import pools, sync, monitor, alerts, plans, dashboard, stocks, ocr, strategy, data

app.include_router(pools.router)
app.include_router(sync.router)
app.include_router(monitor.router)
app.include_router(alerts.router)
app.include_router(plans.router)
app.include_router(dashboard.router)
app.include_router(stocks.router)
app.include_router(ocr.router)
app.include_router(strategy.router)
app.include_router(data.router)

@app.get("/api/health")
def health_check():
    return {"status": "ok"}
