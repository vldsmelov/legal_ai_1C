from fastapi import FastAPI
from .routes.health import router as health_router
from .routes.ingest import router as ingest_router
from .routes.analyze import router as analyze_router
from .startup import register_startup

def create_app() -> FastAPI:
    app = FastAPI(title="Legal AI Backend", version="0.5.0")
    app.include_router(health_router)
    app.include_router(ingest_router)
    app.include_router(analyze_router)
    register_startup(app)  # лёгкие startup-проверки
    return app
