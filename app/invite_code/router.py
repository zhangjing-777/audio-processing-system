from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import get_current_active_user
from app.models import User
from app.schemas import (
    UserResponse,
    UserCreditsResponse,
    UseInviteCodeRequest,
    UseInviteCodeResponse
)
from app.invite_code.service import invite_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/user", tags=["User"])


@router.post("/use-invite-code", response_model=UseInviteCodeResponse)
async def use_invite_code(
    request: UseInviteCodeRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """使用邀请码升级为 Pro"""
    logger.info(f"用户 {current_user.email} 尝试使用邀请码: {request.code}")
    
    success, message = await invite_service.use_invite_code(
        db=db,
        code=request.code,
        user=current_user
    )
    
    if not success:
        logger.warning(f"使用邀请码失败: {message}")
        raise HTTPException(status_code=400, detail=message)
    
    return UseInviteCodeResponse(
        status="success",
        message=message,
        new_level=current_user.user_level
    )


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "service": "user"}
