from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError, jwt
from app.database import get_db
from app.models import User
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)
settings = get_settings()
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    从 JWT token 中获取当前用户
    Token 由 Supabase Auth 签发
    """
    token = credentials.credentials
    
    try:
        # 解码 JWT token
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False}  # Supabase token 不验证 audience
        )
        
        supabase_user_id: str = payload.get("sub")
        if supabase_user_id is None:
            logger.error("Token 中没有 sub 字段")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的认证凭证"
            )
        
        logger.info(f"解析 token 成功，supabase_user_id: {supabase_user_id}")
        
    except JWTError as e:
        logger.error(f"JWT 解码失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证"
        )
    
    # 查询本地用户
    query = select(User).where(User.supabase_user_id == supabase_user_id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if user is None:
        logger.warning(f"用户不存在: {supabase_user_id}，尝试触发同步")
        # 用户不存在，可能是新用户，触发同步
        from app.services.sync_service import sync_single_user
        user = await sync_single_user(supabase_user_id, db)
        
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
    
    logger.info(f"获取用户成功: {user.email}, level={user.user_level}, credits={user.credits}")
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """获取当前激活的用户"""
    if current_user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用"
        )
    return current_user
