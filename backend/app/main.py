from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import actions, cycles, goals, health
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(
    title="Threadline API",
    description=(
        "Backend for Threadline: dependency-aware planning, feasibility "
        "forecasting, disruption replanning, and human-reviewed action "
        "proposals for time-sensitive administrative processes."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Local dev server defaults (Vite, `python3 -m http.server`, VS Code Live
# Server). Add deployed frontend origins here once the app is hosted.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        # Browsers send `Origin: null` for pages opened directly from disk
        # (file://). Allowed here so the frontend prototype works when
        # double-clicked, not just when served - fine for local development,
        # remove before deploying anywhere public.
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    """Safety net for any ValueError raised by the agent workflow that a
    router did not already translate into a specific HTTP status."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


app.include_router(health.router)
app.include_router(goals.router)
app.include_router(cycles.router)
app.include_router(actions.router)
