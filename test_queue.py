import asyncio
from app.core.redis_queue import RedisQueue

async def test_enqueue():
    queue = RedisQueue("ifc_processing_queue")
    job_id = await queue.enqueue({
        "test": True,
        "project_id": "test-123",
        "message": "Hello from test"
    })
    print(f"✅ Test job enqueued: {job_id}")
    
    # Check queue stats
    stats = await queue.get_queue_length()
    print(f"📊 Queue stats: {stats}")

if __name__ == "__main__":
    asyncio.run(test_enqueue())