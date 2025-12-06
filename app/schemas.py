from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ServiceType(str, Enum):
    PIANO = "piano"
    SPLEETER = "spleeter"
    YOURMT3 = "yourmt3"


class ProcessingStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SpleeterStems(int, Enum):
    TWO = 2
    FOUR = 4
    FIVE = 5


# Piano 相关 Schema
class PianoTransRequest(BaseModel):
    pass  # 由 FastAPI 的 UploadFile 处理


class PianoTransResponse(BaseModel):
    status: str
    message: str
    midi_url: Optional[str] = None
    from_cache: bool = False
    job_id: Optional[str] = None


# Spleeter 相关 Schema
class SpleeterRequest(BaseModel):
    stems: SpleeterStems = Field(default=SpleeterStems.TWO, description="音轨数量: 2, 4, 或 5")
    format: str = Field(default="mp3", description="输出格式")
    bitrate: str = Field(default="192k", description="比特率")


class SpleeterFileInfo(BaseModel):
    name: str
    size_kb: float


class SpleeterResponse(BaseModel):
    status: str
    message: str
    download_url: Optional[str] = None
    files: Optional[List[SpleeterFileInfo]] = None
    size_mb: Optional[float] = None
    from_cache: bool = False
    job_id: Optional[str] = None


# YourMT3 相关 Schema
class YourMT3Request(BaseModel):
    pass  # 由 FastAPI 的 UploadFile 处理


class YourMT3Response(BaseModel):
    status: str
    message: str
    midi_url: Optional[str] = None
    from_cache: bool = False
    job_id: Optional[str] = None


# 通用响应
class ErrorResponse(BaseModel):
    status: str = "error"
    message: str
    detail: Optional[str] = None


# 数据库记录 Schema
class ProcessingRecordSchema(BaseModel):
    id: int
    file_hash: str
    original_filename: str
    service_type: str
    input_s3_url: str
    output_s3_url: Optional[str]
    output_data: Optional[Dict[str, Any]]
    status: str
    processing_time: Optional[float]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# 枚举
class UserLevel(str, Enum):
    FREE = "free"
    PRO = "pro"


class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"


class PaymentMethod(str, Enum):
    WECHAT = "wechat"
    STRIPE = "stripe"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


# 用户相关 Schema
class UserBase(BaseModel):
    email: EmailStr
    username: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    email: str
    username: Optional[str]
    user_level: UserLevel
    credits: float
    total_recharged: float
    status: UserStatus
    created_at: datetime
    
    class Config:
        from_attributes = True


class UserCreditsResponse(BaseModel):
    credits: float
    user_level: UserLevel


# 邀请码相关 Schema
class UseInviteCodeRequest(BaseModel):
    code: str = Field(..., description="邀请码")


class UseInviteCodeResponse(BaseModel):
    status: str
    message: str
    new_level: UserLevel


# 充值相关 Schema
class RechargeRequest(BaseModel):
    amount: float = Field(..., gt=0, description="充值金额")

class StripeRechargeRequest(BaseModel):
    price_id: str = Field(..., description="Stripe Price ID")

class StripeSessionResponse(BaseModel):
    session_url: str
    session_id: str


class WechatOrderResponse(BaseModel):
    code_url: str
    order_id: str


class RechargeHistoryItem(BaseModel):
    id: int
    amount: float
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    transaction_id: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class RechargeHistoryResponse(BaseModel):
    total: int
    records: List[RechargeHistoryItem]


# 消费相关 Schema
class ConsumptionHistoryItem(BaseModel):
    id: int
    service_type: str
    audio_duration: float
    credits_cost: float
    status: PaymentStatus
    created_at: datetime
    
    class Config:
        from_attributes = True


class ConsumptionHistoryResponse(BaseModel):
    total: int
    records: List[ConsumptionHistoryItem]


class ConsumptionSummary(BaseModel):
    total_consumption: float
    total_duration: float
    service_breakdown: dict


# 处理历史相关 Schema
class ProcessingHistoryItem(BaseModel):
    id: int
    original_filename: str
    service_type: str
    stems: Optional[int]
    status: str
    audio_duration: Optional[float]
    credits_cost: Optional[float]
    input_s3_url: Optional[str]
    output_s3_url: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class ProcessingHistoryResponse(BaseModel):
    total: int
    records: List[ProcessingHistoryItem]


class ProcessingProgressResponse(BaseModel):
    id: int
    status: str
    original_filename: str
    service_type: str
    progress_percentage: int
    output_s3_url: Optional[str]
    error_message: Optional[str]
    created_at: datetime


# 定价相关 Schema
class PricingItem(BaseModel):
    service_type: str
    user_level: UserLevel
    credits_per_3_minutes: float
    
    class Config:
        from_attributes = True


class PricingListResponse(BaseModel):
    pricing: List[PricingItem]


class CalculatePriceRequest(BaseModel):
    service_type: str
    duration_seconds: float


class CalculatePriceResponse(BaseModel):
    service_type: str
    duration_seconds: float
    duration_minutes: float
    credits_cost_free: float
    credits_cost_pro: float
    user_level: UserLevel
    credits_cost: float
