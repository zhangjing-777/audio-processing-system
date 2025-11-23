import httpx
import logging
import asyncio
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.config import get_settings
from app.models import ProcessingRecord


logger = logging.getLogger(__name__)
settings = get_settings()


class SpleeterService:
    def __init__(self):
        self.api_key = settings.runpod_api_key
        self.endpoint = settings.runpod_spleeter_endpoint
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        logger.info(f"SpleeterService 初始化完成，端点: {self.endpoint}")
    
    async def check_existing_record(
        self,
        db: AsyncSession,
        file_hash: str,
        stems: int
    ) -> Optional[ProcessingRecord]:
        """检查是否已有处理记录(需要匹配stems参数)"""
        logger.info(f"检查是否存在缓存记录，file_hash: {file_hash}, stems: {stems}")
        query = select(ProcessingRecord).where(
            and_(
                ProcessingRecord.file_hash == file_hash,
                ProcessingRecord.service_type == "spleeter",
                ProcessingRecord.stems == stems,
                ProcessingRecord.status == "completed"
            )
        )
        result = await db.execute(query)
        record = result.scalar_one_or_none()
        
        if record:
            logger.info(f"✅ 找到缓存记录，ID: {record.id}, ZIP URL: {record.output_s3_url}")
        else:
            logger.info("未找到缓存记录")
        
        return record
    
    async def create_record(
        self,
        db: AsyncSession,
        file_hash: str,
        original_filename: str,
        input_s3_url: str,
        stems: int
    ) -> ProcessingRecord:
        """创建新的处理记录"""
        logger.info(f"创建数据库记录: file_hash={file_hash}, filename={original_filename}, stems={stems}")
        try:
            record = ProcessingRecord(
                file_hash=file_hash,
                original_filename=original_filename,
                service_type="spleeter",
                input_s3_url=input_s3_url,
                status="processing",
                stems=stems
            )
            db.add(record)
            await db.flush()
            await db.refresh(record)
            logger.info(f"✅ 数据库记录创建成功，ID: {record.id}")
            return record
        except Exception as e:
            logger.error(f"❌ 创建数据库记录失败: {e}", exc_info=True)
            await db.rollback()
            raise Exception(f"创建记录失败: {e}")
    
    async def submit_job(
        self,
        audio_url: str,
        stems: int = 2,
        format: str = "mp3",
        bitrate: str = "192k"
    ) -> str:
        """提交任务到 RunPod，返回 job_id"""
        payload = {
            "input": {
                "audio_url": audio_url,
                "stems": stems,
                "format": format,
                "bitrate": bitrate
            }
        }
        
        logger.info(f"提交任务到 RunPod API: {self.endpoint}")
        logger.debug(f"请求参数: {payload}")
        
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            try:
                response = await client.post(
                    self.endpoint,
                    headers=self.headers,
                    json=payload
                )
                logger.info(f"RunPod API 响应状态码: {response.status_code}")
                response.raise_for_status()
                result = response.json()
                job_id = result.get("id")
                status = result.get("status")
                logger.info(f"✅ 任务提交成功，Job ID: {job_id}, 状态: {status}")
                return job_id
            except Exception as e:
                logger.error(f"❌ 提交任务失败: {e}", exc_info=True)
                raise
    
    async def check_job_status(self, job_id: str) -> Dict[str, Any]:
        """检查任务状态"""
        status_url = f"{self.endpoint.rsplit('/', 1)[0]}/status/{job_id}"
        
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            try:
                response = await client.get(
                    status_url,
                    headers=self.headers
                )
                response.raise_for_status()
                result = response.json()
                return result
            except Exception as e:
                logger.error(f"❌ 查询任务状态失败: {e}")
                raise
    
    async def wait_for_completion(
        self,
        job_id: str,
        max_wait_time: int = 300,
        poll_interval: int = 10
    ) -> Dict[str, Any]:
        """等待任务完成，轮询检查状态"""
        logger.info(f"开始等待任务完成，Job ID: {job_id}, 最大等待时间: {max_wait_time}s")
        
        elapsed_time = 0
        while elapsed_time < max_wait_time:
            result = await self.check_job_status(job_id)
            status = result.get("status")
            
            logger.info(f"任务状态: {status}, 已等待: {elapsed_time}s")
            
            if status == "COMPLETED":
                logger.info(f"✅ 任务完成！")
                return result
            elif status == "FAILED":
                error_msg = result.get("error", "未知错误")
                logger.error(f"❌ 任务失败: {error_msg}")
                raise Exception(f"RunPod 任务失败: {error_msg}")
            elif status in ["IN_QUEUE", "IN_PROGRESS"]:
                logger.info(f"⏳ 任务处理中，{poll_interval}秒后重试...")
                await asyncio.sleep(poll_interval)
                elapsed_time += poll_interval
            else:
                logger.warning(f"⚠️ 未知状态: {status}")
                await asyncio.sleep(poll_interval)
                elapsed_time += poll_interval
        
        raise Exception(f"任务超时：等待 {max_wait_time} 秒后仍未完成")
    
    async def process_audio(
        self,
        audio_url: str,
        stems: int = 2,
        format: str = "mp3",
        bitrate: str = "192k"
    ) -> Dict[str, Any]:
        """提交任务并等待完成"""
        job_id = await self.submit_job(audio_url, stems, format, bitrate)
        result = await self.wait_for_completion(job_id)
        return result
    
    async def update_record_success(
        self,
        db: AsyncSession,
        record: ProcessingRecord,
        result: Dict[str, Any]
    ):
        """更新记录为成功状态"""
        logger.info(f"更新记录为成功状态，记录ID: {record.id}")
        output = result.get("output", {})
        record.status = "completed"
        record.output_s3_url = output.get("download_url")
        record.output_data = {
            "files": output.get("files", []),
            "size_mb": output.get("size_mb"),
            "bitrate": output.get("bitrate"),
            "format": output.get("format")
        }
        record.runpod_job_id = result.get("id")
        record.processing_time = (
            result.get("executionTime", 0) + result.get("delayTime", 0)
        ) / 1000.0
        await db.commit()
        await db.refresh(record)
        logger.info(f"✅ 记录更新成功，ZIP URL: {record.output_s3_url}, 处理时间: {record.processing_time}s")
    
    async def update_record_failure(
        self,
        db: AsyncSession,
        record: ProcessingRecord,
        error_message: str
    ):
        """更新记录为失败状态"""
        logger.warning(f"更新记录为失败状态，记录ID: {record.id}, 错误: {error_message}")
        record.status = "failed"
        record.error_message = error_message
        await db.commit()
        await db.refresh(record)
        logger.info(f"记录失败状态已保存")


# 创建全局实例
spleeter_service = SpleeterService()