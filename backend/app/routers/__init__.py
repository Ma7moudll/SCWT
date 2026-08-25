from .admin import router as admin_router
from .ai import router as ai_router
from .auth import router as auth_router
from .debug import router as debug_router
from .deposit import router as deposit_router
from .rewards import router as rewards_router
from .stations import router as stations_router
from .user_data import router as user_data_router
from .ws import router as ws_router

__all__ = [
    "admin_router",
    "ai_router",
    "auth_router",
    "debug_router",
    "rewards_router",
    "deposit_router",
    "stations_router",
    "user_data_router",
    "ws_router",
]
