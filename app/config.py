from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # AWS S3 配置
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str
    s3_bucket_name: str 
    
    # 数据库配置
    db_host: str
    db_name: str
    db_user: str
    db_password: str
    db_port: int 
    
    # RunPod API 配置
    runpod_api_key: str
    runpod_piano_endpoint: str
    runpod_spleeter_endpoint: str
    runpod_yourmt3_endpoint: str
    
    # Stripe 配置
    stripe_secret_key: str 
    #stripe_publishable_key: str 
    stripe_webhook_secret: str 
    
    # 微信支付配置
    wechat_app_id: str 
    wechat_mch_id: str 
    wechat_api_key: str 
    wechat_notify_url: str
    # wechat_cert_path: str 
    # wechat_key_path: str 
    
    # 定价配置（默认值，可通过数据库覆盖）
    piano_price_free: float 
    piano_price_pro: float 
    spleeter_price_free: float 
    spleeter_price_pro: float
    yourmt3_price_free: float
    yourmt3_price_pro: float 
    
    # 应用配置
    app_name: str 
    debug: bool
    
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
