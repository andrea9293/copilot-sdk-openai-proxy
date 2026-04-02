from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/v1/embeddings")
async def create_embeddings():
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
