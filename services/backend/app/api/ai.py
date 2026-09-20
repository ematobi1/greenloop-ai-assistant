import asyncio

from fastapi import APIRouter, Depends, Query, Request

from app.ai.errors import AiError
from app.ai.providers.base import ModelProvider, ProviderStatus
from app.schemas import ListMeta, ModelList, ModelOut, ProviderList, ProviderOut
from app.security.dependencies import require_token

router = APIRouter(prefix="/v1/ai", tags=["ai"], dependencies=[Depends(require_token)])

STATUS_TIMEOUT_SECONDS = 10.0


async def safe_status(provider: ModelProvider) -> ProviderStatus:
    try:
        return await asyncio.wait_for(provider.status(), STATUS_TIMEOUT_SECONDS)
    except (TimeoutError, AiError):
        return ProviderStatus(available=False, detail="unavailable")


async def safe_models(provider: ModelProvider) -> list[str]:
    try:
        return await asyncio.wait_for(provider.list_models(), STATUS_TIMEOUT_SECONDS)
    except (TimeoutError, AiError):
        return []


@router.get("/providers", response_model=ProviderList)
async def list_providers(request: Request):
    registry = request.app.state.ai_engine.registry
    providers = [registry.get(name) for name in registry.names]
    statuses = await asyncio.gather(*(safe_status(provider) for provider in providers))
    data = [
        ProviderOut(
            name=provider.config.name,
            location=provider.config.location,
            model=provider.config.model or "default",
            available=status.available,
            detail=status.detail,
            default=provider.config.name == registry.default_name,
        )
        for provider, status in zip(providers, statuses, strict=True)
    ]
    return ProviderList(data=data, meta=ListMeta(total=len(data)))


@router.get("/models", response_model=ModelList)
async def list_models(request: Request, provider: str | None = Query(None, max_length=50)):
    registry = request.app.state.ai_engine.registry
    try:
        names = [provider] if provider else registry.names
        selected = [registry.get(name) for name in names]
    except AiError as err:
        raise err.to_api_error() from err
    lists = await asyncio.gather(*(safe_models(item) for item in selected))
    data = [
        ModelOut(
            provider=item.config.name,
            model=model,
            default=item.config.name == registry.default_name
            and model in {item.config.model, "default"},
        )
        for item, models in zip(selected, lists, strict=True)
        for model in models
    ]
    return ModelList(data=data, meta=ListMeta(total=len(data)))
