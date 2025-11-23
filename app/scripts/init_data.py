import asyncio
import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import AsyncSessionLocal
from app.models import InviteCode, ServicePricing, UserLevel
from sqlalchemy import select
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_pricing():
    """初始化服务定价"""
    logger.info("初始化服务定价...")
    
    pricing_data = [
        # Piano Transcription
        {"service_type": "piano", "user_level": UserLevel.FREE, "credits_per_3_minutes": 2.0},
        {"service_type": "piano", "user_level": UserLevel.PRO, "credits_per_3_minutes": 1.5},
        
        # Spleeter
        {"service_type": "spleeter", "user_level": UserLevel.FREE, "credits_per_3_minutes": 3.0},
        {"service_type": "spleeter", "user_level": UserLevel.PRO, "credits_per_3_minutes": 2.25},
        
        # YourMT3
        {"service_type": "yourmt3", "user_level": UserLevel.FREE, "credits_per_3_minutes": 4.0},
        {"service_type": "yourmt3", "user_level": UserLevel.PRO, "credits_per_3_minutes": 3.0},
    ]
    
    async with AsyncSessionLocal() as db:
        try:
            for data in pricing_data:
                # 检查是否已存在
                query = select(ServicePricing).where(
                    ServicePricing.service_type == data["service_type"],
                    ServicePricing.user_level == data["user_level"]
                )
                result = await db.execute(query)
                existing = result.scalar_one_or_none()
                
                if existing:
                    logger.info(f"定价已存在: {data['service_type']} - {data['user_level'].value}")
                    continue
                
                # 创建新定价
                pricing = ServicePricing(**data)
                db.add(pricing)
                logger.info(f"创建定价: {data['service_type']} - {data['user_level'].value} = {data['credits_per_3_minutes']} credits/3min")
            
            await db.commit()
            logger.info("✅ 服务定价初始化完成")
            
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ 初始化定价失败: {e}", exc_info=True)
            raise


async def init_invite_codes():
    """初始化邀请码"""
    logger.info("初始化邀请码...")
    
    invite_codes_data = [
        {
            "code": "PRO2025",
            "target_level": UserLevel.PRO,
            "max_usage": 100,
            "valid_from": datetime.utcnow(),
            "valid_until": datetime.utcnow() + timedelta(days=365),
            "status": "active"
        },
        {
            "code": "EARLYBIRD",
            "target_level": UserLevel.PRO,
            "max_usage": 50,
            "valid_from": datetime.utcnow(),
            "valid_until": datetime.utcnow() + timedelta(days=30),
            "status": "active"
        },
        {
            "code": "TESTPRO",
            "target_level": UserLevel.PRO,
            "max_usage": 10,
            "valid_from": datetime.utcnow(),
            "valid_until": datetime.utcnow() + timedelta(days=7),
            "status": "active"
        }
    ]
    
    async with AsyncSessionLocal() as db:
        try:
            for data in invite_codes_data:
                # 检查是否已存在
                query = select(InviteCode).where(InviteCode.code == data["code"])
                result = await db.execute(query)
                existing = result.scalar_one_or_none()
                
                if existing:
                    logger.info(f"邀请码已存在: {data['code']}")
                    continue
                
                # 创建新邀请码
                invite_code = InviteCode(**data)
                db.add(invite_code)
                logger.info(f"创建邀请码: {data['code']} (上限: {data['max_usage']})")
            
            await db.commit()
            logger.info("✅ 邀请码初始化完成")
            
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ 初始化邀请码失败: {e}", exc_info=True)
            raise


async def main():
    """主函数"""
    logger.info("=" * 50)
    logger.info("开始初始化数据")
    logger.info("=" * 50)
    
    try:
        await init_pricing()
        await init_invite_codes()
        
        logger.info("=" * 50)
        logger.info("✅ 所有数据初始化完成！")
        logger.info("=" * 50)
        
    except Exception as e:
        logger.error(f"❌ 数据初始化失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())