from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.auth.service import do_sync_new_users
from app.invite_code.service import invite_service
from app.database import AsyncSessionLocal
import logging

logger = logging.getLogger(__name__)


class JobScheduler:
    """Handle scheduled tasks"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        logger.info("Job scheduler initialized")
    
    async def sync_new_users_job(self):
        """Scheduled job to sync new users"""
        try:
            logger.info("Running scheduled user synchronization")
            result = await do_sync_new_users()
            logger.info(f"Scheduled sync completed: {result}")
        except Exception as e:
            logger.error(f"Scheduled user sync failed: {e}")
    
    async def validate_invite_codes_job(self):
        """Scheduled job to validate invite codes"""
        try:
            logger.info("Running scheduled invite code validation")
            async with AsyncSessionLocal() as db:
                result = await invite_service.validate_all_users_codes(db)
                logger.info(f"Invite code validation completed: {result}")
        except Exception as e:
            logger.error(f"Scheduled invite code validation failed: {e}")
    
    def start(self):
        """Start the scheduler"""
        # 同步新用户 - 每30秒
        self.scheduler.add_job(
            self.sync_new_users_job,
            'interval',
            seconds=30,
            id='sync_new_users',
            replace_existing=True
        )
        
        # 验证邀请码 - 每24小时
        self.scheduler.add_job(
            self.validate_invite_codes_job,
            'interval',
            hours=24,
            id='validate_invite_codes',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("Job scheduler started with invite code validation")
    
    def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Job scheduler stopped")


# Global scheduler instance
job_scheduler = JobScheduler()
