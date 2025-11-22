from .piano import router as piano_router
from .spleeter import router as spleeter_router
from .yourmt3 import router as yourmt3_router
from .user import router as user_router

__all__ = [
    "piano_router",
    "spleeter_router",
    "yourmt3_router",
    "user_router"
]