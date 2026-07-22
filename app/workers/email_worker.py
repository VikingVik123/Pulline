# app/services/email_worker.py

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from app.core.redis_config import RedisService
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailWorker:
    """Background worker that processes emails from Redis queue."""
    
    def __init__(self):
        self.redis = RedisService()
        self.running = True
        self.batch_size = 10
        
    async def process_email(self, job_data: dict) -> bool:
        """Process a single email job."""
        try:
            to_email = job_data.get("to_email")
            subject = job_data.get("subject")
            html_content = job_data.get("html_content")
            job_id = job_data.get("job_id")
            
            if not all([to_email, subject, html_content]):
                logger.error(f"Invalid email job: {job_id}")
                return False
            
            # Send email
            msg = MIMEMultipart('alternative')
            msg['From'] = settings.MAIL_FROM
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(html_content, 'html'))
            
            if settings.MAIL_SSL:
                smtp_client = smtplib.SMTP_SSL(settings.MAIL_SERVER, settings.MAIL_PORT, timeout=15)
            else:
                smtp_client = smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT, timeout=15)
            
            with smtp_client as server:
                if settings.MAIL_TLS and not settings.MAIL_SSL:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
                server.send_message(msg)
            
            logger.info(f"Email sent successfully: {job_id} to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email {job_id}: {str(e)}")
            return False
    
    async def process_batch(self):
        """Process a batch of emails from Redis queue."""
        processed = 0
        
        for _ in range(self.batch_size):
            # Get job from Redis
            job_data = await self.redis.dequeue_email(timeout=0)
            
            if not job_data:
                break
            
            job_id = job_data.get("job_id")
            to_email = job_data.get("to_email")
            
            try:
                # Process email
                success = await self.process_email(job_data)
                
                # Mark job as sent or failed
                await self.redis.mark_email_sent(
                    job_id,
                    success,
                    error=None if success else "Failed to send"
                )
                
                processed += 1
                
            except Exception as e:
                logger.error(f"Error processing email {job_id}: {e}")
                await self.redis.mark_email_sent(job_id, False, str(e))
        
        return processed
    
    async def run(self):
        """Main worker loop."""
        logger.info("Email worker started, waiting for jobs...")
        print("Started Email worker")
        while self.running:
            try:
                # Process in batches
                processed = await self.process_batch()
                
                if processed == 0:
                    # No jobs, wait a bit
                    await asyncio.sleep(2)
                else:
                    logger.info(f"Processed {processed} emails")
                    
            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(5)
    
    async def stop(self):
        """Stop the worker."""
        self.running = False
        await self.redis.close()
        logger.info("Email worker stopped")


# Singleton worker instance
email_worker = EmailWorker()

if __name__ == "__main__":
    asyncio.run(email_worker.run())