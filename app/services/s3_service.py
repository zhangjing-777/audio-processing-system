import aioboto3
from botocore.exceptions import ClientError
import hashlib
import uuid
import asyncio
from math import ceil
import logging
from app.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)


class S3Service:
    def __init__(self):
        # 初始化 AWS Session
        self.session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region
        )
        self.bucket_name = settings.s3_bucket_name

    def calculate_file_hash(self, file_content: bytes) -> str:
        """计算文件 MD5，用于去重 / 快速比对"""
        return hashlib.md5(file_content).hexdigest()

    def generate_s3_key(self, folder: str, extension: str) -> str:
        """生成唯一 key，确保各类任务互不干扰"""
        unique_id = str(uuid.uuid4())
        return f"{folder}/{unique_id}.{extension}"

    def get_file_url(self, s3_key: str) -> str:
        """根据 key 返回文件 URL（保持原行为）"""
        return f"https://{self.bucket_name}.s3.{settings.aws_region}.amazonaws.com/{s3_key}"

    async def check_file_exists(self, s3_key: str) -> bool:
        """
        异步检查文件是否存在于 S3。
        用 head_object 是官方推荐方式，不会产生下载流量。
        """
        try:
            async with self.session.client("s3") as s3:
                await s3.head_object(Bucket=self.bucket_name, Key=s3_key)
                logger.info(f"[S3] 文件存在: {s3_key}")
                return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                logger.warning(f"[S3] 文件不存在: {s3_key}")
                return False
            logger.error(f"[S3] 无法检查文件是否存在: {e}")
            return False

    async def _multipart_upload(self, file_content: bytes, key: str, content_type: str):
        """
        多分块并发上传（大文件 10~20倍加速）
        分块大小默认 5MB。
        """
        part_size = 5 * 1024 * 1024
        total_parts = ceil(len(file_content) / part_size)

        logger.info(f"[S3] 开始 multipart 上传: key={key}, 大小={len(file_content)/1024/1024:.2f}MB, 分块={total_parts}")

        async with self.session.client("s3") as s3:

            # 创建一个 multipart upload session
            mpu = await s3.create_multipart_upload(
                Bucket=self.bucket_name,
                Key=key,
                ContentType=content_type
            )
            upload_id = mpu["UploadId"]

            async def upload_single_part(part_number: int, offset: int):
                """上传单块"""
                chunk = file_content[offset: offset + part_size]
                resp = await s3.upload_part(
                    Bucket=self.bucket_name,
                    Key=key,
                    PartNumber=part_number,
                    UploadId=upload_id,
                    Body=chunk
                )
                logger.debug(f"[S3] part {part_number}/{total_parts} 上传完成")
                return {"PartNumber": part_number, "ETag": resp["ETag"]}

            # 控制并发（最多 10 个）
            sem = asyncio.Semaphore(10)

            async def sem_task(part_number, offset):
                async with sem:
                    return await upload_single_part(part_number, offset)

            tasks = [
                sem_task(i + 1, i * part_size)
                for i in range(total_parts)
            ]

            # 并发上传所有分块
            parts = await asyncio.gather(*tasks)

            # 按 PartNumber 排序后提交 multipart 完成
            await s3.complete_multipart_upload(
                Bucket=self.bucket_name,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": sorted(parts, key=lambda x: x["PartNumber"])}
            )

        logger.info(f"[S3] multipart 上传完成: key={key}")

    async def upload_file(
        self,
        file_content: bytes,
        folder: str,
        extension: str,
        content_type: str = "audio/mpeg"
    ) -> tuple[str, str]:
        """
        上传文件到 S3（自动优化小文件 & 大文件加速）
        """

        file_hash = self.calculate_file_hash(file_content)
        s3_key = self.generate_s3_key(folder, extension)

        logger.info(f"[S3] 开始上传: key={s3_key}, 大小={len(file_content)} bytes")

        try:
            # 小文件 <5MB → put_object（更快）
            if len(file_content) < 5 * 1024 * 1024:
                async with self.session.client('s3') as s3:
                    await s3.put_object(
                        Bucket=self.bucket_name,
                        Key=s3_key,
                        Body=file_content,
                        ContentType=content_type
                    )
                logger.info(f"[S3] 小文件上传完成: {s3_key}")

            else:
                # 大文件 → multipart upload
                await self._multipart_upload(file_content, s3_key, content_type)

            s3_url = self.get_file_url(s3_key)
            return s3_url, file_hash

        except ClientError as e:
            logger.error(f"[S3] 上传失败: {e}")
            raise Exception(f"S3 上传失败: {str(e)}")


# 全局实例
s3_service = S3Service()
