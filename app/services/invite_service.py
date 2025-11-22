from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import User, InviteCode, InviteCodeUsage
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class InviteService:
    
    async def validate_invite_code(
        self,
        db: AsyncSession,
        code: str,
        user: User
    ) -> tuple[bool, str]:
        """
        验证邀请码
        
        Returns:
            (是否有效, 错误信息)
        """
        # 检查用户是否已使用过邀请码
        if user.invite_code_used:
            return False, "您已经使用过邀请码"
        
        # 检查用户是否已经是 Pro
        if user.user_level.value == 'pro':
            return False, "您已经是 Pro 用户"
        
        # 查询邀请码
        query = select(InviteCode).where(InviteCode.code == code)
        result = await db.execute(query)
        invite_code = result.scalar_one_or_none()
        
        if not invite_code:
            return False, "邀请码不存在"
        
        # 检查状态
        if invite_code.status != 'active':
            return False, "邀请码已失效"
        
        # 检查有效期
        now = datetime.utcnow()
        if invite_code.valid_from and now < invite_code.valid_from:
            return False, "邀请码尚未生效"
        
        if invite_code.valid_until and now > invite_code.valid_until:
            return False, "邀请码已过期"
        
        # 检查使用次数
        if invite_code.max_usage and invite_code.used_count >= invite_code.max_usage:
            return False, "邀请码已达到使用上限"
        
        return True, ""
    
    async def use_invite_code(
        self,
        db: AsyncSession,
        code: str,
        user: User
    ) -> tuple[bool, str]:
        """
        使用邀请码
        
        Returns:
            (是否成功, 消息)
        """
        # 验证邀请码
        is_valid, error_msg = await self.validate_invite_code(db, code, user)
        if not is_valid:
            return False, error_msg
        
        # 查询邀请码
        query = select(InviteCode).where(InviteCode.code == code)
        result = await db.execute(query)
        invite_code = result.scalar_one_or_none()
        
        try:
            # 更新用户等级
            user.user_level = invite_code.target_level
            user.invite_code_used = code
            
            # 增加邀请码使用次数
            invite_code.used_count += 1
            
            # 创建使用记录
            usage = InviteCodeUsage(
                user_id=user.id,
                invite_code_id=invite_code.id
            )
            db.add(usage)
            
            await db.commit()
            await db.refresh(user)
            
            logger.info(f"用户 {user.email} 成功使用邀请码 {code}，升级为 {user.user_level.value}")
            return True, f"恭喜！您已成功升级为 {user.user_level.value.upper()} 用户"
            
        except Exception as e:
            await db.rollback()
            logger.error(f"使用邀请码失败: {e}", exc_info=True)
            return False, "使用邀请码失败，请稍后重试"


# 创建全局实例
invite_service = InviteService()
