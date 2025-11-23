from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # AWS S3 配置
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str = "ap-southeast-1"
    s3_bucket_name: str = "qiupupu"
    
    # 数据库配置
    db_host: str
    db_name: str
    db_user: str
    db_password: str
    db_port: int = 5432
    
    # RunPod API 配置
    runpod_api_key: str
    runpod_piano_endpoint: str
    runpod_spleeter_endpoint: str
    runpod_yourmt3_endpoint: str
    
    # Stripe 配置
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    
    # 微信支付配置
    wechat_app_id: str = ""
    wechat_mch_id: str = ""
    wechat_api_key: str = ""
    wechat_cert_path: str = ""
    wechat_key_path: str = ""
    
    # 定价配置（默认值，可通过数据库覆盖）
    piano_price_free: float = 2.0
    piano_price_pro: float = 1.5
    spleeter_price_free: float = 3.0
    spleeter_price_pro: float = 2.25
    yourmt3_price_free: float = 4.0
    yourmt3_price_pro: float = 3.0
    
    # 应用配置
    app_name: str = "Audio Processing API"
    debug: bool = False
    
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
