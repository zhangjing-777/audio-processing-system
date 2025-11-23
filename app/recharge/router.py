from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.database import get_db
from app.auth import get_current_active_user
from app.models import User, RechargeRecord
from app.schemas import (
    RechargeRequest,
    StripeSessionResponse,
    WechatOrderResponse,
    RechargeHistoryResponse,
    RechargeHistoryItem
)
from app.config import get_settings
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/recharge", tags=["Recharge"])


@router.post("/stripe/create-session", response_model=StripeSessionResponse)
async def create_stripe_session(
    request: RechargeRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """创建 Stripe 支付会话"""
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=501, detail="Stripe 支付未配置")
    
    try:
        import stripe
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
        import stripe
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
                #这样更新内容入库了吗？？？
                
                logger.info(f"Stripe 充值成功: user={user.email}, amount={recharge_record.amount}, new_balance={user.credits}")
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"处理 Stripe Webhook 失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/wechat/create-order", response_model=WechatOrderResponse)
async def create_wechat_order(
    request: RechargeRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """创建微信支付订单"""
    if not settings.wechat_mch_id:
        raise HTTPException(status_code=501, detail="微信支付未配置")
    
    try:
        # 创建充值记录
        recharge_record = RechargeRecord(
            user_id=current_user.user_id,
            amount=request.amount,
            payment_method="wechat",
            payment_status="pending"
        )
        db.add(recharge_record)
        await db.commit()
        await db.refresh(recharge_record)
        
        # TODO: 实现微信支付 Native 支付
        # 这里需要调用微信支付 API 创建订单
        # 返回二维码链接
        
        logger.info(f"创建微信支付订单: user={current_user.email}, amount={request.amount}")
        
        # 示例返回（实际需要调用微信支付 API）
        return WechatOrderResponse(
            code_url="weixin://wxpay/bizpayurl?pr=xxxxx",
            order_id=str(recharge_record.id)
        )
        
    except Exception as e:
        logger.error(f"创建微信支付订单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建支付订单失败: {str(e)}")


@router.post("/wechat/callback")
async def wechat_callback(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """处理微信支付回调"""
    # TODO: 实现微信支付回调处理
    # 验证签名、处理支付结果、更新订单状态
    pass


@router.get("/history", response_model=RechargeHistoryResponse)
async def get_recharge_history(
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """获取充值历史"""
    # 查询总数
    count_query = select(RechargeRecord).where(
        RechargeRecord.user_id == current_user.user_id
    )
    count_result = await db.execute(count_query)
    total = len(count_result.scalars().all())
    
    # 查询记录
    query = select(RechargeRecord).where(
        RechargeRecord.user_id == current_user.user_id
    ).order_by(desc(RechargeRecord.created_at)).offset(skip).limit(limit)
    
    result = await db.execute(query)
    records = result.scalars().all()
    
    logger.info(f"查询充值历史: user={current_user.email}, total={total}")
    
    return RechargeHistoryResponse(
        total=total,
        records=[RechargeHistoryItem.model_validate(r) for r in records]
    )


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "service": "recharge"}