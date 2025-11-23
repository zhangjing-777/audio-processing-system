from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import logging
from app.database import get_db
from app.config import get_settings
from app.get_user import get_user_by_id
from app.models import User, RechargeRecord
from app.schemas import RechargeRequest, WechatOrderResponse
from app.recharge.wechat.service import wechat_pay_service


logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/recharge", tags=["Recharge"])


@router.post("/wechat/create-order", response_model=WechatOrderResponse)
async def create_wechat_order(
    user_id: str,
    request: RechargeRequest,
    db: AsyncSession = Depends(get_db)
):
    """创建微信支付订单"""
    if not settings.wechat_mch_id:
        raise HTTPException(status_code=501, detail="微信支付未配置")
    
    current_user = await get_user_by_id(user_id, db)
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
        
        # 生成商户订单号
        out_trade_no = f"WX{recharge_record.id}{int(datetime.utcnow().timestamp())}"
        
        # 调用微信支付API创建订单
        result = await wechat_pay_service.create_native_order(
            out_trade_no=out_trade_no,
            total_fee=int(request.amount * 100),  # 转换为分
            body=f"充值 {request.amount} credits",
            attach=str(recharge_record.id)  # 附加数据，用于回调时识别订单
        )
        
        # 更新交易ID
        recharge_record.transaction_id = out_trade_no
        await db.commit()
        
        logger.info(f"创建微信支付订单成功: user={current_user.email}, amount={request.amount}, order_id={out_trade_no}")
        
        return WechatOrderResponse(
            code_url=result['code_url'],
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
    try:
        # 读取XML数据
        xml_data = await request.body()
        xml_str = xml_data.decode('utf-8')
        
        logger.info(f"收到微信支付回调")
        logger.debug(f"回调数据: {xml_str}")
        
        # 解析回调数据
        data = wechat_pay_service.parse_notify(xml_str)
        
        # 获取订单号
        out_trade_no = data.get('out_trade_no')
        transaction_id = data.get('transaction_id')
        total_fee = int(data.get('total_fee', 0)) / 100  # 转换为元
        
        logger.info(f"解析回调成功: out_trade_no={out_trade_no}, transaction_id={transaction_id}, total_fee={total_fee}")
        
        # 查询充值记录
        query = select(RechargeRecord).where(
            RechargeRecord.transaction_id == out_trade_no
        )
        result = await db.execute(query)
        recharge_record = result.scalar_one_or_none()
        
        if not recharge_record:
            logger.error(f"充值记录不存在: out_trade_no={out_trade_no}")
            return Response(
                content=wechat_pay_service.generate_notify_response('FAIL', '订单不存在'),
                media_type='application/xml'
            )
        
        # 检查订单状态，避免重复处理
        if recharge_record.payment_status == 'completed':
            logger.warning(f"订单已处理过: out_trade_no={out_trade_no}")
            return Response(
                content=wechat_pay_service.generate_notify_response(),
                media_type='application/xml'
            )
        
        # 验证金额
        if abs(recharge_record.amount - total_fee) > 0.01:
            logger.error(f"金额不匹配: 预期={recharge_record.amount}, 实际={total_fee}")
            return Response(
                content=wechat_pay_service.generate_notify_response('FAIL', '金额不匹配'),
                media_type='application/xml'
            )
        
        # 获取用户
        user_query = select(User).where(User.user_id == recharge_record.user_id)
        user_result = await db.execute(user_query)
        user = user_result.scalar_one_or_none()
        
        if not user:
            logger.error(f"用户不存在: user_id={recharge_record.user_id}")
            return Response(
                content=wechat_pay_service.generate_notify_response('FAIL', '用户不存在'),
                media_type='application/xml'
            )
        
        # 更新用户余额
        user.credits += recharge_record.amount
        user.total_recharged += recharge_record.amount
        
        # 更新充值记录
        recharge_record.payment_status = 'completed'
        recharge_record.completed_at = datetime.utcnow()
        
        await db.commit()
        
        logger.info(f"✅ 微信充值成功: user={user.email}, amount={recharge_record.amount}, new_balance={user.credits}")
        
        # 返回成功响应给微信
        return Response(
            content=wechat_pay_service.generate_notify_response(),
            media_type='application/xml'
        )
        
    except Exception as e:
        logger.error(f"处理微信回调失败: {e}", exc_info=True)
        return Response(
            content=wechat_pay_service.generate_notify_response('FAIL', str(e)),
            media_type='application/xml'
        )


@router.get("/wechat/query/{order_id}")
async def query_wechat_order(
    user_id: str,
    order_id: int,
    db: AsyncSession = Depends(get_db)
):
    """查询微信支付订单状态"""
    current_user = await get_user_by_id(user_id, db)
    try:
        # 查询充值记录
        query = select(RechargeRecord).where(
            RechargeRecord.id == order_id,
            RechargeRecord.user_id == current_user.user_id
        )
        result = await db.execute(query)
        recharge_record = result.scalar_one_or_none()
        
        if not recharge_record:
            raise HTTPException(status_code=404, detail="订单不存在")
        
        # 如果订单已完成，直接返回状态
        if recharge_record.payment_status == 'completed':
            return {
                "status": "completed",
                "amount": recharge_record.amount,
                "completed_at": recharge_record.completed_at
            }
        
        # 查询微信订单状态
        wechat_result = await wechat_pay_service.query_order(recharge_record.transaction_id)
        trade_state = wechat_result.get('trade_state')
        
        logger.info(f"查询微信订单: order_id={order_id}, trade_state={trade_state}")
        
        # 如果微信显示支付成功，但本地未更新，则更新本地状态
        if trade_state == 'SUCCESS' and recharge_record.payment_status == 'pending':
            # 获取用户
            user_query = select(User).where(User.user_id == recharge_record.user_id)
            user_result = await db.execute(user_query)
            user = user_result.scalar_one()
            
            # 更新余额
            user.credits += recharge_record.amount
            user.total_recharged += recharge_record.amount
            
            # 更新记录
            recharge_record.payment_status = 'completed'
            recharge_record.completed_at = datetime.utcnow()
            
            await db.commit()
            
            logger.info(f"补偿更新订单状态: order_id={order_id}")
        
        return {
            "status": "completed" if trade_state == 'SUCCESS' else "pending",
            "amount": recharge_record.amount,
            "trade_state": trade_state,
            "completed_at": recharge_record.completed_at
        }
        
    except Exception as e:
        logger.error(f"查询订单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询订单失败: {str(e)}")
