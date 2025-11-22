from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import User
from app.auth.supabase_client import get_supabase_client
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


async def sync_single_user(supabase_user_id: str, db: AsyncSession) -> User:
    """
    同步单个用户
    
    Args:
        supabase_user_id: Supabase 用户ID
        db: 数据库会话
        
    Returns:
        用户对象
    """
    try:
        # 获取 Supabase 客户端
        supabase = get_supabase_client()
        
        # 从 Supabase 获取用户信息
        response = supabase.auth.admin.get_user_by_id(supabase_user_id)
        supabase_user = response.user
        
        if not supabase_user:
            logger.error(f"Supabase 中未找到用户: {supabase_user_id}")
            return None
        
        logger.info(f"从 Supabase 获取用户信息: {supabase_user.email}")
        
        # 检查本地是否存在
        query = select(User).where(User.supabase_user_id == supabase_user_id)
        result = await db.execute(query)
        user = result.scalar_one_or_none()
        
        if user:
            # 更新现有用户
            user.email = supabase_user.email
            user.username = supabase_user.user_metadata.get('username') or supabase_user.email.split('@')[0]
            user.last_synced_at = datetime.utcnow()
            logger.info(f"更新用户: {user.email}")
        else:
            # 创建新用户
            user = User(
                supabase_user_id=supabase_user_id,
                email=supabase_user.email,
                username=supabase_user.user_metadata.get('username') or supabase_user.email.split('@')[0],
                user_level='free',
                credits=10.0,
                status='active',
                created_at=supabase_user.created_at,
                last_synced_at=datetime.utcnow()
            )
            db.add(user)
            logger.info(f"创建新用户: {user.email}, 初始余额: 10 credits")
        
        await db.commit()
        await db.refresh(user)
        
        return user
        
    except Exception as e:
        logger.error(f"同步用户失败: {e}", exc_info=True)
        await db.rollback()
        return None


async def sync_all_users(db: AsyncSession) -> dict:
    """
    同步所有用户（定时任务）
    
    Args:
        db: 数据库会话
        
    Returns:
        同步统计信息
    """
    stats = {
        'total': 0,
        'created': 0,
        'updated': 0,
        'failed': 0
    }
    
    try:
        # 获取 Supabase 客户端
        supabase = get_supabase_client()
        
        # 获取所有用户（分页）
        page = 1
        per_page = 100
        
        while True:
            logger.info(f"获取用户列表，页码: {page}")
            
            # 获取用户列表
            response = supabase.auth.admin.list_users(page=page, per_page=per_page)
            users = response
            
            if not users or len(users) == 0:
                break
            
            stats['total'] += len(users)
            
            # 处理每个用户
            for supabase_user in users:
                try:
                    # 检查本地是否存在
                    query = select(User).where(User.supabase_user_id == supabase_user.id)
                    result = await db.execute(query)
                    user = result.scalar_one_or_none()
                    
                    if user:
                        # 更新现有用户
                        user.email = supabase_user.email
                        user.username = supabase_user.user_metadata.get('username') or supabase_user.email.split('@')[0]
                        user.last_synced_at = datetime.utcnow()
                        stats['updated'] += 1
                        logger.info(f"更新用户: {user.email}")
                    else:
                        # 创建新用户
                        user = User(
                            supabase_user_id=supabase_user.id,
                            email=supabase_user.email,
                            username=supabase_user.user_metadata.get('username') or supabase_user.email.split('@')[0],
                            user_level='free',
                            credits=10.0,
                            status='active',
                            created_at=supabase_user.created_at,
                            last_synced_at=datetime.utcnow()
                        )
                        db.add(user)
                        stats['created'] += 1
                        logger.info(f"创建新用户: {user.email}")
                    
                    await db.commit()
                    
                except Exception as e:
                    logger.error(f"处理用户失败: {supabase_user.email}, 错误: {e}")
                    stats['failed'] += 1
                    await db.rollback()
            
            # 如果获取的用户数少于 per_page，说明已经是最后一页
            if len(users) < per_page:
                break
            
            page += 1
        
        logger.info(f"用户同步完成: {stats}")
        return stats
        
    except Exception as e:
        logger.error(f"同步所有用户失败: {e}", exc_info=True)
        return stats
