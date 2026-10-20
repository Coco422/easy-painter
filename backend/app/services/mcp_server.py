"""Official SDK transport, independent OAuth identity, existing application services."""
from urllib.parse import urlsplit

from fastapi import HTTPException
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, Field, ValidationError
from typing import Annotated

from app.api import routes
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.user import User
from app.services import agent_auth as auth, agent_tools
from app.services.redis_client import get_redis


class Verifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        from anyio import to_thread
        def verify():
            try:
                resource = auth.resource_url()
                with SessionLocal() as db:
                    grant = auth.verify_access(db, token)
                    return AccessToken(token=token, client_id=grant.client_id, subject=grant.user_id,
                                       scopes=grant.scopes, expires_at=int(auth.as_utc(grant.expires_at).timestamp()),
                                       resource=resource, claims={'grant_id': grant.id})
            except HTTPException:
                return None
        return await to_thread.run_sync(verify)


def build_mcp_server():
    resource = get_settings().mcp_public_url or 'http://127.0.0.1:8000/api/mcp'
    u = urlsplit(resource)
    origin = f'{u.scheme}://{u.netloc}'
    server = MCPServer('Easy Painter', instructions='Generate and edit one image per request using the user’s existing credits. Call list_models and estimate_cost first. Use a stable request_id and explicit max_cost; poll get_job after submission. Never retry an unknown outcome with a new request_id.',
                       token_verifier=Verifier(), auth=AuthSettings(issuer_url=AnyHttpUrl(origin), resource_server_url=AnyHttpUrl(resource), validate_token_resource=True))
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)

    def execute(scope: str | None, fn):
        token = get_access_token()
        if token is None: raise ToolError('请先连接并授权 Easy Painter。')
        try:
            with SessionLocal() as db:
                grant = auth.verify_access(db, token.token)
                if scope and scope not in grant.scopes: raise HTTPException(403, '此连接没有所需权限，请重新授权。')
                return fn(db, grant, db.get(User, grant.user_id))
        except HTTPException as error:
            import json
            raise ToolError(json.dumps({'status': error.status_code, 'detail': error.detail}, ensure_ascii=False)) from None
        except ValidationError:
            raise ToolError('参数格式无效，请检查模型、尺寸和描述。') from None

    @server.tool(annotations=read)
    def list_models() -> dict:
        """List enabled models, image sizes, reference support and personalized per-image prices. Free."""
        return execute(None, lambda db, grant, user: {'models': [m.model_dump() for m in routes.get_public_meta(db=db, settings=get_settings(), current_user=user).models if m.enabled]})

    @server.tool(annotations=read)
    def get_balance() -> dict:
        """Read account credits and this connection's Beijing-calendar-day budget. Free."""
        return execute('account:read', lambda db, grant, user: {'credits': user.credits, 'max_per_job': grant.max_per_job,
                         'daily_limit': grant.daily_limit, 'used_today': auth.daily_usage(db, grant.id), 'timezone': 'Asia/Shanghai'})

    @server.tool(annotations=read)
    def estimate_cost(model: str, size: str = 'auto', editing: bool = False) -> dict:
        """Validate model/size and quote one image; does not reserve credits. Prices are rechecked at submission."""
        return execute(None, lambda db, grant, user: {**agent_tools.estimate(db, user, model, size, editing=editing),
                         'max_per_job': grant.max_per_job, 'daily_remaining': max(0, grant.daily_limit - auth.daily_usage(db, grant.id))})

    @server.tool(annotations=write)
    def generate_image(prompt: Annotated[str, Field(min_length=1, max_length=32000)], model: str,
                       request_id: Annotated[str, Field(min_length=1, max_length=128)],
                       max_cost: Annotated[int, Field(strict=True, ge=0)], size: str = 'auto') -> dict:
        """Submit ONE paid image within the user's authorized budget. Keep request_id AND all parameters unchanged when retrying. Returns job_id immediately; poll get_job. Never invent a new request_id for an unknown outcome."""
        return execute('jobs:create', lambda db, grant, user: agent_tools.submit(db, get_redis(), grant.id, prompt=prompt, model=model, size=size, request_id=request_id, max_cost=max_cost))

    @server.tool(annotations=write)
    def edit_image(source_job_id: str, prompt: Annotated[str, Field(min_length=1, max_length=32000)], model: str,
                   request_id: Annotated[str, Field(min_length=1, max_length=128)],
                   max_cost: Annotated[int, Field(strict=True, ge=0)], size: str = 'auto') -> dict:
        """Submit ONE paid revision from an owned, unexpired job image. Requires jobs:read and jobs:create. Original stays intact. Uses model redrawing, not masks/layer editing. No external URLs or local files. Poll get_job; retry only the exact same request_id and parameters."""
        return execute('jobs:create', lambda db, grant, user: agent_tools.submit(db, get_redis(), grant.id, prompt=prompt, model=model, size=size, request_id=request_id, max_cost=max_cost, source_job_id=source_job_id))

    @server.tool(annotations=read)
    def get_job(job_id: str) -> dict:
        """Read an owned job's status, billing and result. Free. An image_url is a narrow 5-minute download capability, revoked with this connection and bounded by original media expiry; fetch a fresh URL through this tool when needed."""
        return execute('jobs:read', lambda db, grant, user: agent_tools.job_result(db, grant.id, job_id))

    hosts = [u.netloc] + (['127.0.0.1:*', 'localhost:*'] if get_settings().app_env != 'production' else [])
    security = TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=[origin])
    app = server.streamable_http_app(streamable_http_path='/mcp', stateless_http=True, json_response=True,
                                    max_request_body_size=65536, transport_security=security)
    return server, app
