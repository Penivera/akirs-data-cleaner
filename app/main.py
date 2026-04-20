from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api.routes import router

app = FastAPI(title="AKIRS Batch File Cleaner")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include the main router
app.include_router(router)
