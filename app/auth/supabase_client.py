from supabase import create_client, Client
from app.config import get_settings
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


def get_supabase_client() -> Client:
    """获取 Supabase 客户端（使用 service_role_key）"""
    try:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key
        )
        logger.info("Supabase 客户端创建成功")
        return client
    except Exception as e:
        logger.error(f"创建 Supabase 客户端失败: {e}")
        raise
