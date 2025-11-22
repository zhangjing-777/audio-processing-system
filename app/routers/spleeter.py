from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.database import get_db
from app.auth import get_current_active_user
from app.models import User, ProcessingRecord, UserProcessingHistory
from app.schemas import SpleeterResponse, SpleeterFileInfo
from app.services import s3_service, spleeter_service
from app.services.audio_utils import get_audio_duration
from app.services.billing_service import billing_service
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/spleeter", tags=["Spleeter"])


@router.post("/separate", response_model=SpleeterResponse)
async def separate_audio(
    file: UploadFile = File(..., description="音频文件 (MP3/WAV/M4A)"),
    stems: int = Form(default=2, description="音轨数量: 2, 4, 或 5"),
    format: str = Form(default="mp3", description="输出格式"),
    bitrate: str = Form(default="192k", description="比特率"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    音频分离 API (人声/伴奏分离)（含计费）
    
    - 上传音频文件进行音轨分离
    - stems: 2 (人声+伴奏), 4 (人声+鼓+贝斯+其他), 5 (人声+鼓+贝斯+钢琴+其他)
    - 自动计算费用并扣费
    - 如果该文件使用相同参数处理过，将直接返回缓存结果（仍需扣费）
    """
    logger.info(f"========== 开始音频分离请求 ==========")
    logger.info(f"用户: {current_user.email}, 等级: {current_user.user_level.value}, 余额: {current_user.credits}")
    logger.info(f"文件名: {file.filename}, stems: {stems}, format: {format}, bitrate: {bitrate}")
    
    user_history = None
    
    try:
        # 1. 验证stems参数
        if stems not in [2, 4, 5]:
            logger.error(f"stems参数无效: {stems}")
            raise HTTPException(status_code=400, detail="stems参数必须是 2, 4 或 5")
        
        # 2. 读取文件内容
        logger.info("读取上传文件内容...")
        file_content = await file.read()
        logger.info(f"文件读取完成，大小: {len(file_content)} bytes ({len(file_content)/1024/1024:.2f} MB)")
        
        # 3. 获取音频时长
        logger.info("获取音频时长...")
        audio_duration = await get_audio_duration(file_content, file.filename)
        logger.info(f"音频时长: {audio_duration} 秒 ({audio_duration/60:.2f} 分钟)")
        
        # 4. 计算所需费用
        price = await billing_service.get_pricing(db, "spleeter", current_user.user_level.value)
        credits_cost = billing_service.calculate_credits(audio_duration, price)
        logger.info(f"计算费用: {credits_cost} credits (定价: {price} credits/3分钟)")
        
        # 5. 检查余额
        if not await billing_service.check_balance(current_user, credits_cost):
            logger.warning(f"余额不足: 当前={current_user.credits}, 需要={credits_cost}")
            raise HTTPException(
                status_code=402,
                detail=f"余额不足，当前余额: {current_user.credits} credits, 需要: {credits_cost} credits"
            )
        
        # 6. 计算文件哈希
        file_hash = s3_service.calculate_file_hash(file_content)
        logger.info(f"文件哈希: {file_hash}")
        
        # 7. 创建用户处理历史记录
        logger.info("创建用户处理历史记录...")
        user_history = UserProcessingHistory(
            user_id=current_user.id,
            original_filename=file.filename,
            service_type="spleeter",
            stems=stems,
            status="processing",
            audio_duration=audio_duration,
            credits_cost=credits_cost
        )
        db.add(user_history)
        await db.flush()
        await db.refresh(user_history)
        logger.info(f"用户处理历史创建成功，ID: {user_history.id}")
        
        # 8. 检查是否已有处理记录（任何状态，需要匹配stems）
        query = select(ProcessingRecord).where(
            and_(
                ProcessingRecord.file_hash == file_hash,
                ProcessingRecord.service_type == "spleeter",
                ProcessingRecord.stems == stems
            )
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
                    service_type="spleeter",
                    audio_duration=audio_duration
                )
                
                # 更新用户处理历史
                user_history.status = "completed"
                user_history.processing_record_id = existing_record.id
                user_history.consumption_record_id = consumption_record.id
                user_history.output_s3_url = existing_record.output_s3_url
                user_history.completed_at = datetime.utcnow()
                
                await db.commit()
                
                # 解析output_data
                files_info = []
                if existing_record.output_data:
                    files_data = existing_record.output_data.get("files", [])
                    files_info = [SpleeterFileInfo(**f) for f in files_data]
                
                return SpleeterResponse(
                    status="success",
                    message="从缓存返回结果",
                    download_url=existing_record.output_s3_url,
                    files=files_info,
                    size_mb=existing_record.output_data.get("size_mb") if existing_record.output_data else None,
                    from_cache=True,
                    job_id=existing_record.runpod_job_id
                )
            
            # 状态2: processing - 说明正在处理中
            elif existing_record.status == "processing":
                logger.info(f"⏳ 记录正在处理中")
                user_history.status = "processing"
                user_history.processing_record_id = existing_record.id
                await db.commit()
                
                return SpleeterResponse(
                    status="processing",
                    message="任务正在处理中，请稍后查询",
                    download_url=None,
                    files=None,
                    size_mb=None,
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
                existing_record.output_data = None
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
            record = await spleeter_service.create_record(
                db=db,
                file_hash=file_hash,
                original_filename=file.filename,
                input_s3_url=s3_url,
                stems=stems
            )
            
            # 提交事务
            await db.commit()
            logger.info("数据库事务已提交")
        
        # 9. 更新用户处理历史的 input_s3_url
        user_history.input_s3_url = s3_url
        user_history.processing_record_id = record.id
        await db.commit()
        
        # 10. 调用RunPod API处理
        try:
            result = await spleeter_service.process_audio(
                audio_url=s3_url,
                stems=stems,
                format=format,
                bitrate=bitrate
            )
            logger.info(f"RunPod API 返回结果: {result}")
            
            # 检查处理状态
            if result.get("status") == "COMPLETED":
                # 处理成功，计费
                logger.info("处理成功，开始计费...")
                consumption_record = await billing_service.process_billing(
                    db=db,
                    user=current_user,
                    processing_record_id=record.id,
                    service_type="spleeter",
                    audio_duration=audio_duration
                )
                
                # 更新处理记录
                await spleeter_service.update_record_success(db, record, result)
                
                # 更新用户处理历史
                output = result.get("output", {})
                user_history.status = "completed"
                user_history.consumption_record_id = consumption_record.id
                user_history.output_s3_url = output.get("download_url")
                user_history.completed_at = datetime.utcnow()
                
                await db.commit()
                
                # 解析文件列表
                files_data = output.get("files", [])
                files_info = [SpleeterFileInfo(**f) for f in files_data]
                
                logger.info(f"========== 音频分离请求完成 ==========")
                logger.info(f"用户余额: {current_user.credits} credits")
                
                return SpleeterResponse(
                    status="success",
                    message="音频分离完成",
                    download_url=output.get("download_url"),
                    files=files_info,
                    size_mb=output.get("size_mb"),
                    from_cache=False,
                    job_id=result.get("id")
                )
            else:
                error_msg = f"RunPod任务状态异常: {result.get('status')}"
                logger.error(f"❌ {error_msg}")
                
                # 处理失败，不扣费
                await spleeter_service.update_record_failure(db, record, error_msg)
                user_history.status = "failed"
                user_history.error_message = error_msg
                await db.commit()
                
                raise HTTPException(status_code=500, detail=error_msg)
                
        except Exception as e:
            error_msg = f"RunPod API调用失败: {str(e)}"
            logger.error(f"❌ {error_msg}", exc_info=True)
            
            # 处理失败，不扣费
            await spleeter_service.update_record_failure(db, record, error_msg)
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
    return {"status": "healthy", "service": "spleeter"}