from app.api.announcement_routes import announcement_router
from app.api.admin_routes import admin_router
from app.api.auth_routes import auth_router
from app.api.community_admin_routes import community_admin_router
from app.api.inspiration_routes import inspiration_router
from app.api.media_routes import media_router
from app.api.reference_routes import reference_router
from app.api.routes import router
from app.api.user_routes import user_router
from app.api.user_group_routes import user_group_router

__all__ = ["admin_router", "announcement_router", "auth_router", "community_admin_router", "inspiration_router", "media_router", "reference_router", "router", "user_router", "user_group_router"]
