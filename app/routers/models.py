import logging

from fastapi import APIRouter, HTTPException, Request

from app.copilot_manager import get_bearer_token, get_client
from app.schemas import ModelObject, ModelsResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/v1/models", response_model=ModelsResponse)
async def list_models(request: Request):
    github_token = get_bearer_token(request)
    client = await get_client(github_token)
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


@router.get("/v1/models/{model_id}")
async def retrieve_model(model_id: str, request: Request):
    github_token = get_bearer_token(request)
    client = await get_client(github_token)
    models = await client.list_models()

    for m in models:
        if m.id == model_id:
            return ModelObject(id=m.id, owned_by="copilot")

    raise HTTPException(
        status_code=404,
        detail={
            "error": {
                "message": f"The model '{model_id}' does not exist.",
                "type": "invalid_request_error",
                "param": "model",
                "code": "model_not_found",
            }
        },
    )
