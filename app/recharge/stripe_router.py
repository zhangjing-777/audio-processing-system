from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import logging
import stripe
from app.database import get_db
from app.get_user import get_user_by_id
from app.models import User, RechargeRecord
from app.schemas import StripeRechargeRequest, StripeSessionResponse
from app.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/recharge", tags=["Recharge"])

# Stripe Price ID 到积分的映射表
PRICE_TO_POINTS = {
    "price_1Sb0iIDRf8KTd0TlOmOd8Gjy": 10,
    "price_1Sb0jPDRf8KTd0TlivWIQJe7": 20,
    "price_1Sb0jhDRf8KTd0TlPIN7sxR6": 50,
    "price_1Sb0juDRf8KTd0TlxOYM7FEK": 110,
    "price_1Sb0kDDRf8KTd0TlLYfKmfAH": 230,
    "price_1Sb0l1DRf8KTd0TllgDThMVZ": 600,
}


@router.post("/stripe/create-session", response_model=StripeSessionResponse)
async def create_stripe_session(
    user_id: str,
    request: StripeRechargeRequest,
    db: AsyncSession = Depends(get_db)
):
    """创建 Stripe 支付会话（固定档位）"""
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=501, detail="Stripe 支付未配置")
    
    # 验证 price_id 是否在允许的列表中
    if request.price_id not in PRICE_TO_POINTS:
        raise HTTPException(status_code=400, detail=f"无效的 price_id: {request.price_id}")
    
    current_user = await get_user_by_id(user_id, db)
    points = PRICE_TO_POINTS[request.price_id]
    
    try:
        stripe.api_key = settings.stripe_secret_key
        
        # 创建充值记录（amount 字段存储积分值）
        recharge_record = RechargeRecord(
            user_id=current_user.user_id,
            amount=points,  # 存储积分值而不是金额
            payment_method="stripe",
            payment_status="pending"
        )
        db.add(recharge_record)
        await db.commit()
        await db.refresh(recharge_record)
        
        # 创建 Stripe Checkout Session（使用固定 price_id）
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': request.price_id,  # 使用 Stripe 的 Price ID
                'quantity': 1,
            }],
            mode='payment',
            allow_promotion_codes=True,
            success_url=f"{settings.app_name}/recharge/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.app_name}/recharge/cancel",
            metadata={
                'user_id': str(current_user.user_id),
                'recharge_record_id': str(recharge_record.id),
                'price_id': request.price_id  # 记录 price_id 以便 webhook 验证
            }
        )
        
        # 更新交易ID
        recharge_record.transaction_id = session.id
        await db.commit()
        
        logger.info(f"创建 Stripe 支付会话: user={current_user.email}, price_id={request.price_id}, points={points}, session_id={session.id}")
        
        return StripeSessionResponse(
            session_url=session.url,
            session_id=session.id
        )
        
    except Exception as e:
        logger.error(f"创建 Stripe 支付会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建支付会话失败: {str(e)}")


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """处理 Stripe Webhook 回调"""
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=501, detail="Stripe Webhook 未配置")
    
    try:
        stripe.api_key = settings.stripe_secret_key
        
        payload = await request.body()
        sig_header = request.headers.get('stripe-signature')
        
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
        
        # 处理支付成功事件
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            
            # 从 metadata 中获取 recharge_record_id
            recharge_record_id = session['metadata'].get('recharge_record_id')
            price_id = session['metadata'].get('price_id')
            
            if not recharge_record_id:
                logger.error("Webhook 缺少 recharge_record_id")
                return {"status": "error", "message": "Missing recharge_record_id"}
            
            if not price_id or price_id not in PRICE_TO_POINTS:
                logger.error(f"无效的 price_id: {price_id}")
                return {"status": "error", "message": "Invalid price_id"}
            
            # 获取充值记录
            query = select(RechargeRecord).where(
                RechargeRecord.id == int(recharge_record_id)
            )
            result = await db.execute(query)
            recharge_record = result.scalar_one_or_none()
            
            if not recharge_record:
                logger.error(f"充值记录不存在: recharge_record_id={recharge_record_id}")
                return {"status": "error", "message": "Recharge record not found"}
            
            if recharge_record.payment_status == 'completed':
                logger.warning(f"订单已处理过: recharge_record_id={recharge_record_id}")
                return {"status": "success", "message": "Already processed"}
            
            # 从映射表获取积分值
            points = PRICE_TO_POINTS[price_id]
            
            # 获取用户
            user_query = select(User).where(User.user_id == recharge_record.user_id)
            user_result = await db.execute(user_query)
            user = user_result.scalar_one()
            
            # 增加积分
            user.credits += points
            user.total_recharged += points
            
            # 更新充值记录
            recharge_record.payment_status = 'completed'
            recharge_record.completed_at = datetime.utcnow()
            
            await db.commit()
            
            logger.info(f"✅ Stripe 充值成功: user={user.email}, price_id={price_id}, points={points}, new_balance={user.credits}")
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"处理 Stripe Webhook 失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))