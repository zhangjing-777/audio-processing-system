from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct, text
from app.database import get_db
from app.models import User, ProcessingRecord
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/statistics", tags=["Statistics"])


@router.get("/users/count")
async def get_user_count(db: AsyncSession = Depends(get_db)):
    """
    统计用户数量
    
    返回 user_info 表中去重的 user_id 数量
    """
    try:
        # 统计去重的 user_id 数量
        query = select(func.count(distinct(User.user_id)))
        result = await db.execute(query)
        count = result.scalar()
        
        logger.info(f"📊 用户统计: 总用户数={count}")
        
        return {
            "status": "success",
            "total_users": count,
            "message": f"当前共有 {count} 个用户"
        }
        
    except Exception as e:
        logger.error(f"❌ 统计用户数量失败: {e}", exc_info=True)
        return {
            "status": "error",
            "total_users": 0,
            "message": f"统计失败: {str(e)}"
        }


@router.get("/songs/processed")
async def get_processed_songs_count(db: AsyncSession = Depends(get_db)):
    """
    统计处理完成的歌曲数量
    
    统计 processing_records 表中 status 为 'completed' 的
    唯一 (file_hash, service_type, stems) 组合数量
    
    使用原生 SQL 直接利用数据库的 COUNT(DISTINCT ...) 功能，性能最优
    """
    try:
        # 方法1：使用原生 SQL（推荐，性能最好）
        # PostgreSQL 支持 COUNT(DISTINCT (col1, col2, col3)) 语法
        total_query = text("""
            SELECT COUNT(DISTINCT (file_hash, service_type, stems))
            FROM processing_records
            WHERE status = 'completed'
        """)
        
        result = await db.execute(total_query)
        count = result.scalar()
        
        # 按服务类型分组统计
        breakdown_query = text("""
            SELECT service_type, COUNT(DISTINCT (file_hash, service_type, stems)) as count
            FROM processing_records
            WHERE status = 'completed'
            GROUP BY service_type
        """)
        
        breakdown_result = await db.execute(breakdown_query)
        breakdown = {row.service_type: row.count for row in breakdown_result}
        
        logger.info(f"📊 歌曲处理统计: 总处理数={count}, 分类={breakdown}")
        
        return {
            "status": "success",
            "total_processed": count,
            "breakdown_by_service": breakdown,
            "message": f"已成功处理 {count} 首歌曲"
        }
        
    except Exception as e:
        logger.error(f"❌ 统计处理歌曲数量失败: {e}", exc_info=True)
        return {
            "status": "error",
            "total_processed": 0,
            "breakdown_by_service": {},
            "message": f"统计失败: {str(e)}"
        }


@router.get("/overview")
async def get_statistics_overview(db: AsyncSession = Depends(get_db)):
    """
    统计总览
    
    返回所有关键统计数据，使用原生 SQL 优化性能
    """
    try:
        # 1. 统计用户数量
        user_query = select(func.count(distinct(User.user_id)))
        user_result = await db.execute(user_query)
        total_users = user_result.scalar()
        
        # 2. 统计处理完成的歌曲数量（原生 SQL）
        songs_query = text("""
            SELECT COUNT(DISTINCT (file_hash, service_type, stems))
            FROM processing_records
            WHERE status = 'completed'
        """)
        songs_result = await db.execute(songs_query)
        total_processed = songs_result.scalar()
        
        # 3. 按服务类型分组统计（原生 SQL）
        breakdown_query = text("""
            SELECT service_type, COUNT(DISTINCT (file_hash, service_type, stems)) as count
            FROM processing_records
            WHERE status = 'completed'
            GROUP BY service_type
        """)
        breakdown_result = await db.execute(breakdown_query)
        breakdown = {row.service_type: row.count for row in breakdown_result}
        
        # 4. 统计用户等级分布
        user_level_query = select(
            User.user_level,
            func.count(distinct(User.user_id)).label('count')
        ).group_by(
            User.user_level
        )
        user_level_result = await db.execute(user_level_query)
        user_level_breakdown = {row.user_level.value: row.count for row in user_level_result}
        
        logger.info(f"📊 统计总览: 用户={total_users}, 处理歌曲={total_processed}")
        
        return {
            "status": "success",
            "users": {
                "total": total_users,
                "by_level": user_level_breakdown
            },
            "processed_songs": {
                "total": total_processed,
                "by_service": breakdown
            },
            "message": "统计数据获取成功"
        }
        
    except Exception as e:
        logger.error(f"❌ 获取统计总览失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"统计失败: {str(e)}"
        }