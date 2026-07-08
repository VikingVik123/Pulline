import asyncio
from app.core.redis_queue import RedisQueue

async def test_dequeue():
    queue = RedisQueue("ifc_processing_queue")
    
    # Check pending jobs
    stats = await queue.get_queue_length()
    print(f"📊 Queue stats: {stats}")
    
    # Try to dequeue one
    job = await queue.dequeue()
    if job:
        print(f"✅ Dequeued job: {job.get('job_id')}")
        print(f"   Data: {job}")
    else:
        print("❌ No jobs to dequeue")

if __name__ == "__main__":
    asyncio.run(test_dequeue())