from app.api.admin_routes import admin_router
from app.api.auth_routes import auth_router
from app.api.routes import router
from app.api.user_routes import user_router

__all__ = ["admin_router", "auth_router", "router", "user_router"]
