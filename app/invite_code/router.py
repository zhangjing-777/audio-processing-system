from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.get_user import get_user_by_id
from app.schemas import UseInviteCodeRequest, UseInviteCodeResponse
from app.invite_code.service import invite_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/invite-code", tags=["InviteCode"])


@router.post("/use", response_model=UseInviteCodeResponse)
async def use_invite_code(
    user_id: str,
    request: UseInviteCodeRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    使用邀请码升级为 Pro
    
    规则：
    - 用户必须是 FREE 才能使用邀请码
    - 如果已经是 PRO（正在使用其他邀请码），必须等待邀请码失效降级后才能使用新邀请码
    - 不支持叠加使用邀请码
    """
    # 获取用户对象
    current_user = await get_user_by_id(user_id, db)
    
    logger.info(f"用户 {current_user.email} 尝试使用邀请码: {request.code}")
    
    success, message = await invite_service.use_invite_code(
        db=db,
        code=request.code,
        user=current_user
    )
    
    if not success:
        logger.warning(f"使用邀请码失败: {message}")
        raise HTTPException(status_code=400, detail=message)
    
    # 刷新用户对象以获取最新状态
    await db.refresh(current_user)
    
    return UseInviteCodeResponse(
        status="success",
        message=message,
        new_level=current_user.user_level
    )


@router.post("/validate-all")
async def validate_all_codes(db: AsyncSession = Depends(get_db)):
    """
    手动触发验证所有用户的邀请码（管理员接口）
    
    检查所有 Pro 用户的邀请码有效性，自动降级失效的用户
    """
    logger.info("手动触发邀请码验证")
    result = await invite_service.validate_all_users_codes(db)
    return result


@router.get("/check/{code}")
async def check_invite_code(
    code: str,
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    检查邀请码对当前用户是否有效
    
    返回邀请码的详细信息和对当前用户的可用性
    """
    current_user = await get_user_by_id(user_id, db)
    
    is_valid, error_msg, invite_code = await invite_service.check_code_validity_for_user(
        db, code, user_id
    )
    
    if not invite_code:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    
    # 获取用户使用次数
    usage_count = await invite_service.get_user_code_usage_count(
        db, user_id, invite_code.id
    )
    
    return {
        "code": invite_code.code,
        "is_valid": is_valid,
        "error_message": error_msg if not is_valid else None,
        "target_level": invite_code.target_level.value,
        "max_usage_per_user": invite_code.max_usage,
        "your_usage_count": usage_count,
        "valid_from": invite_code.valid_from,
        "valid_until": invite_code.valid_until,
        "status": invite_code.status,
        "current_user_level": current_user.user_level.value,
        "current_using_code": current_user.invite_code_used
    }
