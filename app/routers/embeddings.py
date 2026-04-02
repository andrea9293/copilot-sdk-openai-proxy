from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.copilot_manager import get_bearer_token

router = APIRouter()


@router.post("/v1/embeddings")
async def create_embeddings(request: Request):
    get_bearer_token(request)
    return JSONResponse(
        status_code=501,
        content={
            "error": {
                "message": "Embeddings are not supported by the Copilot SDK. This endpoint is not implemented.",
                "type": "not_implemented",
                "param": None,
                "code": "not_implemented",
            }
        },
    )
