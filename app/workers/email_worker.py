# app/services/email_worker.py

import asyncio
import logging
from app.core.redis_config import RedisService
from app.core.email import EmailService

logger = logging.getLogger(__name__)


class EmailWorker:
    """Background worker that processes emails from Redis queue."""
    
    def __init__(self):
        self.redis = RedisService()
        self.running = True
        self.batch_size = 10
        
    async def process_email(self, job_data: dict) -> bool:
        """Process a single email job by dispatching to EmailService based on type."""
        try:
            to_email = job_data.get("to_email")
            email_type = job_data.get("email_type")
            token = job_data.get("token")
            job_id = job_data.get("job_id")

            if not to_email or not email_type:
                logger.error(f"Invalid email job: {job_id}")
                return False

            if email_type == "verification":
                result = await asyncio.to_thread(
                    EmailService.send_verification_email, to_email, token
                )
            elif email_type == "password_reset":
                result = await asyncio.to_thread(
                    EmailService.send_password_reset_email, to_email, token
                )
            elif email_type == "welcome":
                result = await asyncio.to_thread(
                    EmailService.send_welcome_email, to_email
                )
            else:
                logger.error(f"Unknown email_type '{email_type}' for job: {job_id}")
                return False

            success = result and result.get("success", False)
            
            if success:
                logger.info(f"✅ Email sent: {job_id} to {to_email}")
            else:
                logger.error(f"❌ Failed: {job_id} - {result.get('message', 'Unknown')}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed: {str(e)}", exc_info=True)
            return False
    
    async def process_batch(self):
        """Process a batch of emails from Redis queue."""
        processed = 0
        
        for _ in range(self.batch_size):
            job_data = await self.redis.dequeue_email(timeout=0)
            
            if not job_data:
                break
            
            job_id = job_data.get("job_id")
            
            try:
                success = await self.process_email(job_data)
                await self.redis.mark_email_sent(job_id, success, error=None if success else "Failed")
                if success:
                    processed += 1
            except Exception as e:
                logger.error(f"Error: {e}", exc_info=True)
                await self.redis.mark_email_sent(job_id, False, str(e))
        
        return processed
    
    async def run(self):
        """Main worker loop."""
        logger.info("📧 Email worker started")
        print("📧 Started Email worker")
        
        while self.running:
            try:
                processed = await self.process_batch()
                if processed == 0:
                    await asyncio.sleep(2)
                else:
                    print(f"✅ Processed {processed} emails")
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def stop(self):
        self.running = False
        await self.redis.close()


email_worker = EmailWorker()

if __name__ == "__main__":
    asyncio.run(email_worker.run())