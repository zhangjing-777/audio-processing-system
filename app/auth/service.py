from fastapi import HTTPException
from sqlalchemy import text
import logging
from app.database import AsyncSessionLocal
from app.models import User

logger = logging.getLogger(__name__)

async def do_sync_new_users():
    async with AsyncSessionLocal() as db:
        try:
            logger.info("Starting sync_new_users job...")

            query = text("""
                SELECT u.id, u.email
                FROM auth.users u
                LEFT JOIN public.user_info ul ON ul.user_id = u.id
                WHERE ul.user_id IS NULL
                    and u.email IS NOT NULL;
            """)
            
            result = await db.execute(query)
            rows = result.fetchall()
            
            logger.info(f"Found {len(rows)} new users to sync:{rows}")

            if not rows:
                logger.info("No new users found. Sync finished.")
                return {
                    "message": "No new users to sync",
                    "inserted": {
                        "user_info": 0
                    },
                    "status": "success"
                }

            user_objects = []
            for row in rows:
                user_objects.append(
                    User(
                        user_id=row.id,
                        email=row.email
                    )
                )

            if user_objects:
                db.add_all(user_objects)
                logger.info(f"Added {len(user_objects)} records to user_info")

            await db.commit()
            logger.info("All records committed successfully")

            return {
                "message": "Sync completed",
                "inserted": {
                    "user_info": len(user_objects)
                },
                "status": "success"
            }

        except Exception as e:
            await db.rollback()
            logger.exception(f"sync_new_users failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
