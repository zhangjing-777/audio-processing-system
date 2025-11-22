from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models import User, UserProcessingHistory, ConsumptionRecord
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


class UserService:
    
    async def get_user_by_id(self, db: AsyncSession, user_id: int) -> Optional[User]:
        """根据ID获取用户"""
        query = select(User).where(User.id == user_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_user_by_supabase_id(self, db: AsyncSession, supabase_user_id: str) -> Optional[User]:
        """根据Supabase ID获取用户"""
        query = select(User).where(User.supabase_user_id == supabase_user_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_consumption_summary(self, db: AsyncSession, user_id: int) -> Dict:
        """
        获取用户消费汇总
        
        Returns:
            {
                'total_consumption': 总消费,
                'total_duration': 总时长,
                'service_breakdown': {服务类型: 消费金额}
            }
        """
        # 总消费和总时长
        query = select(
            func.sum(ConsumptionRecord.credits_cost).label('total_cost'),
            func.sum(ConsumptionRecord.audio_duration).label('total_duration')
        ).where(
            ConsumptionRecord.user_id == user_id,
            ConsumptionRecord.status == 'completed'
        )
        result = await db.execute(query)
        row = result.first()
        
        total_consumption = float(row.total_cost or 0)
        total_duration = float(row.total_duration or 0)
        
        # 按服务类型分组统计
        query = select(
            ConsumptionRecord.service_type,
            func.sum(ConsumptionRecord.credits_cost).label('cost')
        ).where(
            ConsumptionRecord.user_id == user_id,
            ConsumptionRecord.status == 'completed'
        ).group_by(ConsumptionRecord.service_type)
        
        result = await db.execute(query)
        rows = result.fetchall()
        
        service_breakdown = {row.service_type: float(row.cost) for row in rows}
        
        return {
            'total_consumption': total_consumption,
            'total_duration': total_duration,
            'service_breakdown': service_breakdown
        }


# 创建全局实例
user_service = UserService()
