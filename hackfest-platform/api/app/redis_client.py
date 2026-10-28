import os
import redis.asyncio as redis

_client: redis.Redis | None = None

def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    return _client

# Submission queue: worker pops from here.
SUBMISSION_QUEUE = "hackfest:submissions"

# Leaderboard sorted set per event: key = f"hackfest:leaderboard:{event_id}"
# Score encoding trick: score = points * 1_000_000_000 - seconds_since_event_start
# Higher points always sorts first; among equal points, whoever got there first
# (smaller seconds_since_event_start, so a LARGER subtracted score) sorts first.
def leaderboard_key(event_id: str) -> str:
    return f"hackfest:leaderboard:{event_id}"

def encode_score(points: int, seconds_since_start: int) -> float:
    return points * 1_000_000_000 - seconds_since_start
