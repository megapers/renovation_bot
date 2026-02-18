"""
Admin API for tenant management (multi-tenant SaaS).

Run standalone:
    uvicorn bot.admin_api:app --port 8080

Or import and mount on an existing FastAPI app.

Endpoints:
    GET  /tenants          — list all tenants
    POST /tenants          — create a new tenant
    GET  /tenants/{id}     — get tenant details
    PUT  /tenants/{id}     — update tenant (name, is_active)
    DELETE /tenants/{id}   — deactivate a tenant

Authentication: For MVP, use a shared admin API key via X-Admin-Key header.
Production should use proper auth (OAuth2, JWT, etc.).
"""

import logging
from typing import Sequence

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from bot.config import settings
from bot.db.models import Tenant
from bot.db.repositories import (
    create_tenant,
    get_all_active_tenants,
    get_tenant_by_bot_token,
)
from bot.db.session import async_session_factory

logger = logging.getLogger(__name__)

app = FastAPI(title="Renovation Bot Admin API", version="1.0.0")


# ── Auth ──────────────────────────────────────────────────────

ADMIN_API_KEY = settings.telegram_bot_token  # Reuse bot token as admin key for MVP


async def verify_admin_key(x_admin_key: str = Header(...)) -> None:
    """Simple API key check. Replace with proper auth in production."""
    if x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")


# ── Schemas ───────────────────────────────────────────────────


class TenantCreate(BaseModel):
    name: str
    telegram_bot_token: str


class TenantOut(BaseModel):
    id: int
    name: str
    telegram_bot_token: str
    telegram_bot_username: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class TenantUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


# ── Endpoints ─────────────────────────────────────────────────


@app.get("/tenants", response_model=list[TenantOut])
async def list_tenants(_: None = Depends(verify_admin_key)):
    """List all active tenants."""
    async with async_session_factory() as session:
        tenants = await get_all_active_tenants(session)
        return [TenantOut.model_validate(t) for t in tenants]


@app.post("/tenants", response_model=TenantOut, status_code=201)
async def create_tenant_endpoint(
    body: TenantCreate,
    _: None = Depends(verify_admin_key),
):
    """Register a new tenant (bot instance).

    The caller must first create a Telegram bot via @BotFather and
    provide the token here. The bot will be started on next restart
    (or hot-reloaded if that feature is implemented).
    """
    async with async_session_factory() as session:
        # Check for duplicate token
        existing = await get_tenant_by_bot_token(session, body.telegram_bot_token)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Tenant with this bot token already exists (id={existing.id})",
            )

        tenant = await create_tenant(
            session,
            name=body.name,
            telegram_bot_token=body.telegram_bot_token,
        )
        await session.commit()
        return TenantOut.model_validate(tenant)


@app.get("/tenants/{tenant_id}", response_model=TenantOut)
async def get_tenant(tenant_id: int, _: None = Depends(verify_admin_key)):
    """Get a single tenant by ID."""
    async with async_session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return TenantOut.model_validate(tenant)


@app.put("/tenants/{tenant_id}", response_model=TenantOut)
async def update_tenant(
    tenant_id: int,
    body: TenantUpdate,
    _: None = Depends(verify_admin_key),
):
    """Update tenant name or active status."""
    async with async_session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        if body.name is not None:
            tenant.name = body.name
        if body.is_active is not None:
            tenant.is_active = body.is_active
        await session.commit()
        return TenantOut.model_validate(tenant)


@app.delete("/tenants/{tenant_id}", status_code=204)
async def deactivate_tenant(
    tenant_id: int,
    _: None = Depends(verify_admin_key),
):
    """Deactivate a tenant (soft delete). Bot will stop on next restart."""
    async with async_session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        tenant.is_active = False
        await session.commit()
