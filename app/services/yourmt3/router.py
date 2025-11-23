from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import logging
from app.database import get_db
from app.auth import get_current_active_user
from app.models import User, ProcessingRecord, UserProcessingHistory
from app.schemas import YourMT3Response
from app.services.s3_service import s3_service
from app.services.audio_utils import get_audio_duration
from app.services.billing_service import billing_service
from app.services.yourmt3.service import yourmt3_service


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/yourmt3", tags=["YourMT3"])


@router.post("/transcribe", response_model=YourMT3Response)
async def transcribe_multitrack(
    file: UploadFile = File(..., description="音频文件 (MP3/WAV/M4A)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    多轨扒谱 API（含计费）
    
    - 上传音频文件进行多轨扒谱处理
    - 自动计算费用并扣费
    - 如果该文件之前已处理过，将直接返回缓存结果（仍需扣费）
    """
    logger.info(f"========== 开始多轨扒谱请求 ==========")
    logger.info(f"用户: {current_user.email}, 等级: {current_user.user_level.value}, 余额: {current_user.credits}")
    logger.info(f"文件名: {file.filename}, Content-Type: {file.content_type}")
    
    user_history = None
    
    try:
        # 1. 读取文件内容
        logger.info("读取上传文件内容...")
        file_content = await file.read()
        logger.info(f"文件读取完成，大小: {len(file_content)} bytes ({len(file_content)/1024/1024:.2f} MB)")
        
        # 2. 获取音频时长
        logger.info("获取音频时长...")
        audio_duration = await get_audio_duration(file_content, file.filename)
        logger.info(f"音频时长: {audio_duration} 秒 ({audio_duration/60:.2f} 分钟)")
        
        # 3. 计算所需费用
        price = await billing_service.get_pricing(db, "yourmt3", current_user.user_level.value)
        credits_cost = billing_service.calculate_credits(audio_duration, price)
        logger.info(f"计算费用: {credits_cost} credits (定价: {price} credits/3分钟)")
        
        # 4. 检查余额
        if not await billing_service.check_balance(current_user, credits_cost):
            logger.warning(f"余额不足: 当前={current_user.credits}, 需要={credits_cost}")
            raise HTTPException(
                status_code=402,
                detail=f"余额不足，当前余额: {current_user.credits} credits, 需要: {credits_cost} credits"
            )
        
        # 5. 计算文件哈希
        file_hash = s3_service.calculate_file_hash(file_content)
        logger.info(f"文件哈希: {file_hash}")
        
        # 6. 创建用户处理历史记录
        logger.info("创建用户处理历史记录...")
        user_history = UserProcessingHistory(
            user_id=current_user.id,
            original_filename=file.filename,
            service_type="yourmt3",
            status="processing",
            audio_duration=audio_duration,
            credits_cost=credits_cost
        )
        db.add(user_history)
        await db.flush()
        await db.refresh(user_history)
        logger.info(f"用户处理历史创建成功，ID: {user_history.id}")
        
        # 7. 检查是否已有处理记录（任何状态）
        query = select(ProcessingRecord).where(
            ProcessingRecord.file_hash == file_hash,
            ProcessingRecord.service_type == "yourmt3"
        ).order_by(ProcessingRecord.created_at.desc())
        result = await db.execute(query)
        existing_record = result.scalar_one_or_none()
        
        # 根据记录状态处理
        if existing_record:
            logger.info(f"找到已存在记录，ID: {existing_record.id}, 状态: {existing_record.status}")
            
            # 状态1: completed 且有输出URL - 直接返回缓存（但仍需扣费）
            if existing_record.status == "completed" and existing_record.output_s3_url:
                logger.info(f"✅ 记录已完成且有结果，返回缓存（仍需扣费）")
                
                # 扣费
                consumption_record = await billing_service.process_billing(
                    db=db,
                    user=current_user,
                    processing_record_id=existing_record.id,
                    service_type="yourmt3",
                    audio_duration=audio_duration
                )
                
                # 更新用户处理历史
                user_history.status = "completed"
                user_history.processing_record_id = existing_record.id
                user_history.consumption_record_id = consumption_record.id
                user_history.output_s3_url = existing_record.output_s3_url
                user_history.completed_at = datetime.utcnow()
                
                await db.commit()
                
                return YourMT3Response(
                    status="success",
                    message="从缓存返回结果",
                    midi_url=existing_record.output_s3_url,
                    from_cache=True,
                    job_id=existing_record.runpod_job_id
                )
            
            # 状态2: processing - 说明正在处理中
            elif existing_record.status == "processing":
                logger.info(f"⏳ 记录正在处理中")
                user_history.status = "processing"
                user_history.processing_record_id = existing_record.id
                await db.commit()
                
                return YourMT3Response(
                    status="processing",
                    message="任务正在处理中，请稍后查询",
                    midi_url=None,
                    from_cache=False,
                    job_id=existing_record.runpod_job_id
                )
            
            # 状态3: failed 或 completed但没有输出 - 重新处理
            else:
                logger.info(f"⚠️ 记录状态异常，重新处理")
                
                # 检查是否已有S3 URL
                if existing_record.input_s3_url:
                    logger.info(f"复用已有S3 URL: {existing_record.input_s3_url}")
                    s3_url = existing_record.input_s3_url
                else:
                    # 重新上传到S3
                    file_extension = file.filename.split(".")[-1] if "." in file.filename else "mp3"
                    s3_url, _ = await s3_service.upload_file(
                        file_content=file_content,
                        folder="url2mp3",
                        extension=file_extension,
                        content_type=file.content_type or "audio/mpeg"
                    )
                    existing_record.input_s3_url = s3_url
                
                # 重置记录状态
                existing_record.status = "processing"
                existing_record.output_s3_url = None
                existing_record.error_message = None
                await db.commit()
                await db.refresh(existing_record)
                
                record = existing_record
        
        else:
            # 没有记录 - 创建新记录
            logger.info("未找到已存在记录，创建新记录")
            
            # 获取文件扩展名
            file_extension = file.filename.split(".")[-1] if "." in file.filename else "mp3"
            
            # 上传到S3
            s3_url, _ = await s3_service.upload_file(
                file_content=file_content,
                folder="url2mp3",
                extension=file_extension,
                content_type=file.content_type or "audio/mpeg"
            )
            
            # 创建处理记录
            record = await yourmt3_service.create_record(
                db=db,
                file_hash=file_hash,
                original_filename=file.filename,
                input_s3_url=s3_url
            )
            
            # 提交事务
            await db.commit()
            logger.info("数据库事务已提交")
        
        # 8. 更新用户处理历史的 input_s3_url
        user_history.input_s3_url = s3_url
        user_history.processing_record_id = record.id
        await db.commit()
        
        # 9. 调用RunPod API处理
        try:
            result = await yourmt3_service.process_audio(s3_url)
            logger.info(f"RunPod API 返回结果: {result}")
            
            # 检查处理状态
            if result.get("status") == "COMPLETED":
                # 处理成功，计费
                logger.info("处理成功，开始计费...")
                consumption_record = await billing_service.process_billing(
                    db=db,
                    user=current_user,
                    processing_record_id=record.id,
                    service_type="yourmt3",
                    audio_duration=audio_duration
                )
                
                # 更新处理记录
                await yourmt3_service.update_record_success(db, record, result)
                
                # 更新用户处理历史
                midi_url = result.get("output", {}).get("midi_url")
                user_history.status = "completed"
                user_history.consumption_record_id = consumption_record.id
                user_history.output_s3_url = midi_url
                user_history.completed_at = datetime.utcnow()
                
                await db.commit()
                
                logger.info(f"========== 多轨扒谱请求完成 ==========")
                logger.info(f"用户余额: {current_user.credits} credits")
                
                return YourMT3Response(
                    status="success",
                    message="多轨扒谱完成",
                    midi_url=midi_url,
                    from_cache=False,
                    job_id=result.get("id")
                )
            else:
                error_msg = f"RunPod任务状态异常: {result.get('status')}"
                logger.error(f"❌ {error_msg}")
                
                # 处理失败，不扣费
                await yourmt3_service.update_record_failure(db, record, error_msg)
                user_history.status = "failed"
                user_history.error_message = error_msg
                await db.commit()
                
                raise HTTPException(status_code=500, detail=error_msg)
                
        except Exception as e:
            error_msg = f"RunPod API调用失败: {str(e)}"
            logger.error(f"❌ {error_msg}", exc_info=True)
            
            # 处理失败，不扣费
            await yourmt3_service.update_record_failure(db, record, error_msg)
            user_history.status = "failed"
            user_history.error_message = error_msg
            await db.commit()
            
            raise HTTPException(status_code=500, detail=error_msg)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 处理失败: {str(e)}", exc_info=True)
        
        # 更新用户处理历史为失败
        if user_history:
            user_history.status = "failed"
            user_history.error_message = str(e)
            await db.commit()
        
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "service": "yourmt3"}