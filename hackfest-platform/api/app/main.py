import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import teams, events, challenges, submissions, leaderboard, admin

app = FastAPI(title="Hackfest Platform API")

# Comma-separated list of your real frontend origins, e.g.
#   ALLOWED_ORIGINS=https://hackfest.example.com
# Falls back to "*" so local development keeps working when it's unset —
# set it before a real event.
_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(teams.router)
app.include_router(events.router)
app.include_router(challenges.router)
app.include_router(submissions.router)
app.include_router(leaderboard.router)
app.include_router(admin.router)

@app.get("/health")
async def health():
    return {"ok": True}
