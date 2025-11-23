from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import logging
import stripe
from app.database import get_db
from app.get_user import get_user_by_id
from app.models import User, RechargeRecord
from app.schemas import RechargeRequest, StripeSessionResponse
from app.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/recharge", tags=["Recharge"])


@router.post("/stripe/create-session", response_model=StripeSessionResponse)
async def create_stripe_session(
    user_id: str,
    request: RechargeRequest,
    db: AsyncSession = Depends(get_db)
):
    """创建 Stripe 支付会话"""
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=501, detail="Stripe 支付未配置")
    
    current_user = await get_user_by_id(user_id, db)
    try:
        stripe.api_key = settings.stripe_secret_key
        
        # 创建充值记录
        recharge_record = RechargeRecord(
            user_id=current_user.user_id,
            amount=request.amount,
            payment_method="stripe",
            payment_status="pending"
        )
        db.add(recharge_record)
        await db.commit()
        await db.refresh(recharge_record)
        
        # 创建 Stripe Checkout Session
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Credits Recharge',
                    },
                    'unit_amount': int(request.amount * 100),  # 转换为分
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"{settings.app_name}/recharge/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.app_name}/recharge/cancel",
            metadata={
                'user_id': str(current_user.user_id),
                'recharge_record_id': str(recharge_record.id)
            }
        )
        
        # 更新交易ID
        recharge_record.transaction_id = session.id
        await db.commit()
        
        logger.info(f"创建 Stripe 支付会话: user={current_user.email}, amount={request.amount}, session_id={session.id}")
        
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
            
            # 获取充值记录
            transaction_id = session['id']
            query = select(RechargeRecord).where(
                RechargeRecord.transaction_id == transaction_id
            )
            result = await db.execute(query)
            recharge_record = result.scalar_one_or_none()
            
            if recharge_record and recharge_record.payment_status == 'pending':
                # 获取用户
                user_query = select(User).where(User.user_id == recharge_record.user_id)
                user_result = await db.execute(user_query)
                user = user_result.scalar_one()
                
                # 增加余额
                user.credits += recharge_record.amount
                user.total_recharged += recharge_record.amount
                
                # 更新充值记录
                recharge_record.payment_status = 'completed'
                recharge_record.completed_at = datetime.utcnow()
                
                await db.commit()
                
                logger.info(f"Stripe 充值成功: user={user.email}, amount={recharge_record.amount}, new_balance={user.credits}")
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"处理 Stripe Webhook 失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
