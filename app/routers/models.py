import logging

from fastapi import APIRouter

from app.copilot_manager import get_client
from app.schemas import ModelObject, ModelsResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/v1/models", response_model=ModelsResponse)
async def list_models():
    client = get_client()
    models = await client.list_models()

    data: list[ModelObject] = []
    for m in models:
        data.append(
            ModelObject(
                id=m.id,
                owned_by="copilot",
            )
        )

    return ModelsResponse(data=data)
