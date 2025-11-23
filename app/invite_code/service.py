from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models import User, InviteCode, InviteCodeUsage, UserLevel
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class InviteService:
    
    async def check_code_validity_for_user(
        self,
        db: AsyncSession,
        code: str,
        user_id: str
    ) -> tuple[bool, str, InviteCode | None]:
        """
        检查邀请码对特定用户是否有效
        
        Args:
            db: 数据库会话
            code: 邀请码
            user_id: 用户ID
            
        Returns:
            (是否有效, 错误信息, 邀请码对象)
        """
        # 1. 查询邀请码
        query = select(InviteCode).where(InviteCode.code == code)
        result = await db.execute(query)
        invite_code = result.scalar_one_or_none()
        
        if not invite_code:
            return False, "邀请码不存在", None
        
        # 2. 检查状态
        if invite_code.status != 'active':
            return False, "邀请码已失效", invite_code
        
        # 3. 检查有效期
        now = datetime.utcnow()
        if invite_code.valid_from and now < invite_code.valid_from:
            return False, "邀请码尚未生效", invite_code
        
        if invite_code.valid_until and now > invite_code.valid_until:
            return False, "邀请码已过期", invite_code
        
        # 4. 检查该用户使用此邀请码的次数（如果设置了上限）
        if invite_code.max_usage is not None:
            usage_count = await self.get_user_code_usage_count(db, user_id, invite_code.id)
            if usage_count >= invite_code.max_usage:
                return False, f"您已使用此邀请码{usage_count}次，已达到上限", invite_code
        
        return True, "", invite_code
    
    async def get_user_code_usage_count(
        self,
        db: AsyncSession,
        user_id: str,
        invite_code_id: int
    ) -> int:
        """
        获取特定用户使用某个邀请码的次数
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            invite_code_id: 邀请码ID
            
        Returns:
            使用次数
        """
        query = select(func.count()).select_from(InviteCodeUsage).where(
            InviteCodeUsage.user_id == user_id,
            InviteCodeUsage.invite_code_id == invite_code_id
        )
        result = await db.execute(query)
        count = result.scalar() or 0
        
        logger.debug(f"用户 {user_id} 使用邀请码 {invite_code_id} 的次数: {count}")
        return count
    
    async def use_invite_code(
        self,
        db: AsyncSession,
        code: str,
        user: User
    ) -> tuple[bool, str]:
        """
        用户使用邀请码升级为 Pro
        
        规则：
        1. 用户当前必须是 FREE 才能使用邀请码
        2. 如果用户已经使用了邀请码（是 PRO），必须等降级为 FREE 后才能使用新邀请码
        3. 不能叠加使用邀请码
        
        Args:
            db: 数据库会话
            code: 邀请码
            user: 用户对象
            
        Returns:
            (是否成功, 消息)
        """
        logger.info(f"用户 {user.email} 尝试使用邀请码: {code}")
        
        # 1. 检查用户当前状态
        if user.user_level == UserLevel.PRO:
            if user.invite_code_used:
                logger.warning(f"用户 {user.email} 已使用邀请码 {user.invite_code_used}，不能叠加使用")
                return False, f"您当前正在使用邀请码 '{user.invite_code_used}'，无法叠加使用新邀请码。请等待当前邀请码失效后再使用新的邀请码。"
            else:
                logger.warning(f"用户 {user.email} 已经是 PRO 用户")
                return False, "您已经是 Pro 用户"
        
        # 2. 检查邀请码对该用户是否有效
        is_valid, error_msg, invite_code = await self.check_code_validity_for_user(
            db, code, user.user_id
        )
        
        if not is_valid:
            logger.warning(f"邀请码 {code} 对用户 {user.email} 无效: {error_msg}")
            return False, error_msg
        
        try:
            # 3. 更新用户等级和邀请码
            user.user_level = invite_code.target_level
            user.invite_code_used = code
            
            # 4. 创建使用记录
            usage = InviteCodeUsage(
                user_id=user.user_id,
                invite_code_id=invite_code.id
            )
            db.add(usage)
            
            await db.commit()
            await db.refresh(user)
            
            logger.info(f"✅ 用户 {user.email} 成功使用邀请码 {code}，升级为 {user.user_level.value}")
            return True, f"恭喜！您已成功升级为 {user.user_level.value.upper()} 用户"
            
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ 使用邀请码失败: {e}", exc_info=True)
            return False, "使用邀请码失败，请稍后重试"

    async def validate_all_users_codes(self, db: AsyncSession) -> dict:
        """
        验证所有 Pro 用户的邀请码有效性，自动降级失效的用户
        
        检查逻辑：
        1. 邀请码是否在有效期内
        2. 邀请码状态是否为 active
        3. 用户使用该邀请码的次数是否超过 max_usage
        
        Returns:
            处理结果统计
        """
        logger.info("开始验证所有用户的邀请码有效性")
        
        # 查询所有使用了邀请码的 Pro 用户
        query = select(User).where(
            User.user_level == UserLevel.PRO,
            User.invite_code_used.isnot(None)
        )
        result = await db.execute(query)
        pro_users = result.scalars().all()
        
        logger.info(f"找到 {len(pro_users)} 个 Pro 用户需要验证")
        
        downgraded_users = []
        valid_users = []
        
        for user in pro_users:
            logger.info(f"验证用户: {user.email}, 邀请码: {user.invite_code_used}")
            
            # 检查邀请码对该用户是否仍然有效
            is_valid, error_msg, invite_code = await self.check_code_validity_for_user(
                db, user.invite_code_used, user.user_id
            )
            
            if not is_valid:
                # 邀请码失效，降级用户
                logger.warning(f"⚠️ 用户 {user.email} 的邀请码 '{user.invite_code_used}' 已失效: {error_msg}")
                
                old_code = user.invite_code_used
                
                # 更新用户表：降级为 FREE，清空邀请码
                user.user_level = UserLevel.FREE
                user.invite_code_used = None
                
                # 这里已经修改了 user 对象，因为 user 是从数据库查询出来的实体
                # SQLAlchemy 会自动追踪这些修改
                
                downgraded_users.append({
                    "email": user.email,
                    "user_id": user.user_id,
                    "old_code": old_code,
                    "reason": error_msg
                })
                
                logger.info(f"✅ 用户 {user.email} 已降级为 FREE")
            else:
                valid_users.append({
                    "email": user.email,
                    "user_id": user.user_id,
                    "code": user.invite_code_used
                })
                logger.info(f"✓ 用户 {user.email} 的邀请码仍然有效")
        
        # 提交所有更改到数据库
        try:
            await db.commit()
            logger.info(f"✅ 数据库更新成功：降级了 {len(downgraded_users)} 个用户")
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ 数据库更新失败: {e}", exc_info=True)
            raise Exception(f"数据库更新失败: {e}")
        
        result = {
            "total_checked": len(pro_users),
            "valid_count": len(valid_users),
            "downgraded_count": len(downgraded_users),
            "downgraded_users": downgraded_users,
            "valid_users": valid_users,
            "status": "success"
        }
        
        logger.info("=" * 50)
        logger.info(f"邀请码验证完成:")
        logger.info(f"  - 总检查数: {result['total_checked']}")
        logger.info(f"  - 有效用户: {result['valid_count']}")
        logger.info(f"  - 降级用户: {result['downgraded_count']}")
        logger.info("=" * 50)
        
        return result


# 创建全局实例
invite_service = InviteService()