from redis.asyncio import Redis

RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


async def consume_request(
    redis: Redis, key: str, window_seconds: int
) -> tuple[int, int]:
    result = await redis.eval(RATE_LIMIT_SCRIPT, 1, key, window_seconds)
    return int(result[0]), int(result[1])
