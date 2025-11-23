from sqlalchemy import Column, String, Integer, DateTime, Float, JSON, UniqueConstraint, Index, Boolean, ForeignKey, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

Base = declarative_base()


# 枚举类型
class UserLevel(str, enum.Enum):
    FREE = "free"
    PRO = "pro"


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"


class PaymentMethod(str, enum.Enum):
    WECHAT = "wechat"
    STRIPE = "stripe"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class ProcessingStatus(str, enum.Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# 用户表
class User(Base):
    """用户表"""
    __tablename__ = "user_info"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, nullable=False, index=True, comment="Supabase Auth用户ID")
    email = Column(String, unique=True, nullable=False, index=True, comment="邮箱")
    user_level = Column(SQLEnum(UserLevel), default=UserLevel.FREE, nullable=False, comment="用户等级")
    credits = Column(Float, default=10.0, nullable=False, comment="当前余额")
    total_recharged = Column(Float, default=0.0, comment="累计充值金额")
    invite_code_used = Column(String, default=0.0, comment="当前使用的邀请码")
    status = Column(SQLEnum(UserStatus), default=UserStatus.ACTIVE, nullable=False, comment="账户状态")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    recharge_records = relationship("RechargeRecord", back_populates="user")
    consumption_records = relationship("ConsumptionRecord", back_populates="user")
    processing_history = relationship("UserProcessingHistory", back_populates="user")
    
    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, level={self.user_level}, credits={self.credits})>"


# 邀请码表
class InviteCode(Base):
    """邀请码表"""
    __tablename__ = "invite_codes"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False, index=True, comment="邀请码")
    target_level = Column(SQLEnum(UserLevel), default=UserLevel.PRO, nullable=False, comment="目标等级")
    max_usage = Column(Integer, comment="最大使用次数")
    valid_from = Column(DateTime, comment="生效时间")
    valid_until = Column(DateTime, comment="失效时间")
    status = Column(String, default="active", comment="状态")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    usage_records = relationship("InviteCodeUsage", back_populates="invite_code")
    
    def __repr__(self):
        return f"<InviteCode(code={self.code}, used={self.used_count}/{self.max_usage})>"


# 邀请码使用记录表
class InviteCodeUsage(Base):
    """邀请码使用记录表"""
    __tablename__ = "invite_code_usage"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("user_info.user_id"), nullable=False)
    invite_code_id = Column(Integer, ForeignKey("invite_codes.id"), nullable=False)
    used_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    user = relationship("User")
    invite_code = relationship("InviteCode", back_populates="usage_records")


# 充值记录表
class RechargeRecord(Base):
    """充值记录表"""
    __tablename__ = "recharge_records"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("user_info.user_id"), nullable=False, index=True)
    amount = Column(Float, nullable=False, comment="充值金额")
    payment_method = Column(SQLEnum(PaymentMethod), nullable=False, comment="支付方式")
    payment_status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False, comment="支付状态")
    transaction_id = Column(String, comment="第三方交易ID")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, comment="完成时间")
    
    # 关系
    user = relationship("User", back_populates="recharge_records")
    
    def __repr__(self):
        return f"<RechargeRecord(id={self.id}, user_id={self.user_id}, amount={self.amount}, status={self.payment_status})>"


# 消费记录表
class ConsumptionRecord(Base):
    """消费记录表"""
    __tablename__ = "consumption_records"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("user_info.user_id"), nullable=False, index=True)
    processing_record_id = Column(Integer, ForeignKey("processing_records.id"), nullable=False)
    service_type = Column(String, nullable=False, comment="服务类型")
    audio_duration = Column(Float, nullable=False, comment="音频时长(秒)")
    credits_cost = Column(Float, nullable=False, comment="扣费金额")
    status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.COMPLETED, nullable=False, comment="状态")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # 关系
    user = relationship("User", back_populates="consumption_records")
    processing_record = relationship("ProcessingRecord")
    
    def __repr__(self):
        return f"<ConsumptionRecord(id={self.id}, user_id={self.user_id}, cost={self.credits_cost})>"


# 用户处理历史表
class UserProcessingHistory(Base):
    """用户处理历史表"""
    __tablename__ = "user_processing_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("user_info.user_id"), nullable=False, index=True)
    processing_record_id = Column(Integer, ForeignKey("processing_records.id"))
    consumption_record_id = Column(Integer, ForeignKey("consumption_records.id"))
    original_filename = Column(String, nullable=False, comment="原始文件名")
    service_type = Column(String, nullable=False, comment="服务类型")
    stems = Column(Integer, comment="Spleeter stems参数")
    input_s3_url = Column(String, comment="输入文件S3 URL")
    output_s3_url = Column(String, comment="输出文件S3 URL")
    status = Column(SQLEnum(ProcessingStatus), default=ProcessingStatus.PROCESSING, nullable=False, comment="状态")
    audio_duration = Column(Float, comment="音频时长(秒)")
    credits_cost = Column(Float, comment="扣费金额")
    error_message = Column(String, comment="错误信息")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, comment="完成时间")
    
    # 关系
    user = relationship("User", back_populates="processing_history")
    processing_record = relationship("ProcessingRecord")
    consumption_record = relationship("ConsumptionRecord")
    
    def __repr__(self):
        return f"<UserProcessingHistory(id={self.id}, user_id={self.user_id}, status={self.status})>"


class ProcessingRecord(Base):
    """音频处理记录表（文件级缓存）"""
    __tablename__ = "processing_records"
    
    id = Column(Integer, primary_key=True, index=True)
    file_hash = Column(String, nullable=False, index=True, comment="文件MD5哈希值")
    original_filename = Column(String, nullable=False, comment="原始文件名")
    service_type = Column(String, nullable=False, index=True, comment="服务类型: piano/spleeter/yourmt3")
    input_s3_url = Column(String, nullable=False, comment="输入音频S3 URL")
    output_s3_url = Column(String, comment="输出结果S3 URL")
    output_data = Column(JSON, comment="额外的输出数据(如spleeter的文件列表)")
    status = Column(String, default="processing", comment="状态: processing/completed/failed")
    runpod_job_id = Column(String, comment="RunPod任务ID")
    error_message = Column(String, comment="错误信息")
    processing_time = Column(Float, comment="处理时间(秒)")
    stems = Column(Integer, comment="Spleeter stems参数")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 组合唯一约束
    __table_args__ = (
        UniqueConstraint('file_hash', 'service_type', 'stems', name='uq_file_service_stems'),
        Index('ix_file_hash_service_stems', 'file_hash', 'service_type', 'stems'),
    )
    
    def __repr__(self):
        return f"<ProcessingRecord(id={self.id}, file_hash={self.file_hash}, service_type={self.service_type})>"


# 服务定价配置表
class ServicePricing(Base):
    """服务定价配置表"""
    __tablename__ = "service_pricing"
    
    id = Column(Integer, primary_key=True, index=True)
    service_type = Column(String, nullable=False, comment="服务类型")
    user_level = Column(SQLEnum(UserLevel), nullable=False, comment="用户等级")
    credits_per_3_minutes = Column(Float, nullable=False, comment="每3分钟费用")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('service_type', 'user_level', name='uq_service_level'),
    )
    
    def __repr__(self):
        return f"<ServicePricing(service={self.service_type}, level={self.user_level}, price={self.credits_per_3_minutes})>"
