from fastapi import APIRouter, Request

router = APIRouter(tags=["models"])


@router.get("/models")
async def list_models(request: Request) -> dict:
    generation = getattr(request.app.state, "chat_generation", None)
    if generation is None:
        return {"models": []}
    return {
        "models": [
            {"id": item.id, "display_name": item.display_name, "description": item.description}
            for item in generation.catalog.display()
        ]
    }
