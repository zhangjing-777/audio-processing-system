from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
from app.config import get_settings
from app.database import init_db, close_db
from app.auth.scheduler import job_scheduler
from app.auth.router import router as auth_router
from app.services.piano.router import router as piano_router
from app.services.spleeter.router import router as spleeter_router
from app.services.yourmt3.router import router as yourmt3_router
from app.recharge.router import router as recharge_router
from app.invite_code.router import router as code_router

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理（启动 + 关闭）"""
    logger.info("[LIFESPAN] 应用启动中...")

    # 1. 初始化数据库
    try:
        logger.info("初始化数据库...")
        await init_db()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")

    # 2. 启动定时任务
    try:
        logger.info("启动任务调度器...")
        job_scheduler.start()
        logger.info("任务调度器已启动")
    except Exception as e:
        logger.error(f"任务调度器启动失败: {e}")

    logger.info("[LIFESPAN] 应用启动完成")

    # 交给 FastAPI 控制
    yield

    logger.info("[LIFESPAN] 应用关闭中...")

    # 停止调度器
    try:
        logger.info("停止任务调度器...")
        job_scheduler.stop()
        logger.info("任务调度器已停止")
    except Exception as e:
        logger.error(f"停止调度器失败: {e}")

    # 关闭数据库
    try:
        logger.info("关闭数据库连接...")
        await close_db()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.error(f"数据库关闭失败: {e}")

    logger.info("[LIFESPAN] 应用关闭完成")


# 创建 FastAPI 应用
app = FastAPI(
    title="Audio Processing API",
    description="音频处理后端服务 - 支持钢琴扒谱、音频分离、多轨扒谱",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境需要设置具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"全局异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "服务器内部错误",
            "detail": str(exc) if settings.debug else None
        }
    )


# 注册路由
app.include_router(auth_router)
app.include_router(piano_router)
app.include_router(spleeter_router)
app.include_router(yourmt3_router)
app.include_router(code_router)
app.include_router(recharge_router)


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "Audio Processing API",
        "version": "1.0.0",
        "services": [
            "Piano Transcription (PianoTrans)",
            "Audio Separation (Spleeter)",
            "Multi-track Transcription (YourMT3)"
        ],
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "message": "Service is running"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )
