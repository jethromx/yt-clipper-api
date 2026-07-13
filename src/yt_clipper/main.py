from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from yt_clipper.config import get_settings
from yt_clipper.interfaces.http.routes import health_router, router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(router)
    return app


app = create_app()
