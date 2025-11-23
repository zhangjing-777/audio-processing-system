from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import User
import logging

logger = logging.getLogger(__name__)


async def get_user_by_id(user_id: str, db: AsyncSession) -> User:
    """
    通过 user_id 获取 User 对象
    
    Args:
        user_id: 用户ID字符串
        db: 数据库会话
        
    Returns:
        User 对象
        
    Raises:
        HTTPException: 用户不存在或账户被禁用
    """
    logger.info(f"获取用户信息: user_id={user_id}")
    
    query = select(User).where(User.user_id == user_id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        logger.error(f"用户不存在: user_id={user_id}")
        raise HTTPException(status_code=404, detail="用户不存在")
    
    if user.status.value != 'active':
        logger.error(f"用户账户已被禁用: user_id={user_id}, status={user.status}")
        raise HTTPException(status_code=403, detail="账户已被禁用")
    
    logger.info(f"用户验证成功: email={user.email}, level={user.user_level.value}")
    return user