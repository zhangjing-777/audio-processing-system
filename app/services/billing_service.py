from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import User, ServicePricing, ConsumptionRecord, UserProcessingHistory
from math import ceil
import logging

logger = logging.getLogger(__name__)


class BillingService:
    
    # 默认定价（如果数据库中没有配置）
    DEFAULT_PRICING = {
        'piano': {'free': 2.0, 'pro': 1.5},
        'spleeter': {'free': 3.0, 'pro': 2.25},
        'yourmt3': {'free': 4.0, 'pro': 3.0}
    }
    
    async def get_pricing(
        self,
        db: AsyncSession,
        service_type: str,
        user_level: str
    ) -> float:
        """
        获取服务定价（每3分钟的费用）
        
        Args:
            db: 数据库会话
            service_type: 服务类型
            user_level: 用户等级
            
        Returns:
            每3分钟的费用
        """
        # 先从数据库查询
        query = select(ServicePricing).where(
            ServicePricing.service_type == service_type,
            ServicePricing.user_level == user_level,
            ServicePricing.is_active == True
        )
        result = await db.execute(query)
        pricing = result.scalar_one_or_none()
        
        if pricing:
            logger.info(f"从数据库获取定价: {service_type}/{user_level} = {pricing.credits_per_3_minutes}")
            return pricing.credits_per_3_minutes
        
        # 使用默认定价
        default_price = self.DEFAULT_PRICING.get(service_type, {}).get(user_level, 2.0)
        logger.info(f"使用默认定价: {service_type}/{user_level} = {default_price}")
        return default_price
    
    def calculate_credits(
        self,
        duration_seconds: float,
        price_per_3_minutes: float
    ) -> float:
        """
        计算所需 credits
        
        Args:
            duration_seconds: 音频时长（秒）
            price_per_3_minutes: 每3分钟的费用
            
        Returns:
            所需 credits
        """
        duration_minutes = duration_seconds / 60
        billing_units = ceil(duration_minutes / 3)  # 向上取整到3分钟单位
        total_credits = billing_units * price_per_3_minutes
        
        logger.info(f"计费计算: {duration_seconds}秒 = {duration_minutes:.2f}分钟 = {billing_units}个计费单位 × {price_per_3_minutes} = {total_credits} credits")
        return total_credits
    
    async def check_balance(
        self,
        user: User,
        required_credits: float
    ) -> bool:
        """
        检查用户余额是否足够
        
        Args:
            user: 用户对象
            required_credits: 所需 credits
            
        Returns:
            是否足够
        """
        is_sufficient = user.credits >= required_credits
        logger.info(f"余额检查: 用户={user.email}, 当前余额={user.credits}, 所需={required_credits}, 结果={'充足' if is_sufficient else '不足'}")
        return is_sufficient
    
    async def deduct_credits(
        self,
        db: AsyncSession,
        user: User,
        amount: float
    ):
        """
        扣除用户 credits（使用事务）
        
        Args:
            db: 数据库会话
            user: 用户对象
            amount: 扣除金额
        """
        if user.credits < amount:
            raise Exception(f"余额不足: 当前={user.credits}, 需要={amount}")
        
        old_balance = user.credits
        user.credits -= amount
        await db.commit()
        await db.refresh(user)
        
        logger.info(f"扣费成功: 用户={user.email}, {old_balance} - {amount} = {user.credits}")
    
    async def create_consumption_record(
        self,
        db: AsyncSession,
        user_id: int,
        processing_record_id: int,
        service_type: str,
        audio_duration: float,
        credits_cost: float
    ) -> ConsumptionRecord:
        """
        创建消费记录
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            processing_record_id: 处理记录ID
            service_type: 服务类型
            audio_duration: 音频时长
            credits_cost: 扣费金额
            
        Returns:
            消费记录
        """
        record = ConsumptionRecord(
            user_id=user_id,
            processing_record_id=processing_record_id,
            service_type=service_type,
            audio_duration=audio_duration,
            credits_cost=credits_cost,
            status="completed"
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
        
        logger.info(f"创建消费记录: ID={record.id}, 用户={user_id}, 费用={credits_cost}")
        return record
    
    async def process_billing(
        self,
        db: AsyncSession,
        user: User,
        processing_record_id: int,
        service_type: str,
        audio_duration: float
    ) -> ConsumptionRecord:
        """
        完整的计费流程（扣费 + 创建记录）
        
        Args:
            db: 数据库会话
            user: 用户对象
            processing_record_id: 处理记录ID
            service_type: 服务类型
            audio_duration: 音频时长
            
        Returns:
            消费记录
        """
        # 获取定价
        price = await self.get_pricing(db, service_type, user.user_level.value)
        
        # 计算费用
        credits_cost = self.calculate_credits(audio_duration, price)
        
        # 检查余额
        if not await self.check_balance(user, credits_cost):
            raise Exception(f"余额不足，当前余额: {user.credits}, 需要: {credits_cost}")
        
        # 扣费
        await self.deduct_credits(db, user, credits_cost)
        
        # 创建消费记录
        consumption_record = await self.create_consumption_record(
            db=db,
            user_id=user.id,
            processing_record_id=processing_record_id,
            service_type=service_type,
            audio_duration=audio_duration,
            credits_cost=credits_cost
        )
        
        await db.commit()
        logger.info(f"计费完成: 用户={user.email}, 服务={service_type}, 费用={credits_cost}")
        
        return consumption_record


# 创建全局实例
billing_service = BillingService()
