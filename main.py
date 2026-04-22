from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api.routes import router as main_router
from app.api.analytics import router as analytics_router

app = FastAPI(title="AKIRS Batch File Cleaner")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(main_router)
app.include_router(analytics_router)
