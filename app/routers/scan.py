import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_api_key
from app.models import Product, ProductTag
from app.schemas import ProductOut, ScanRequest, ScanResult
from app.ws import manager

router = APIRouter(tags=["scan"])

logger = logging.getLogger("uvicorn.error")


@router.post(
    "/scan",
    response_model=ScanResult,
    dependencies=[Depends(require_api_key)],
)
async def scan(payload: ScanRequest, db: Session = Depends(get_db)) -> ScanResult:
    product = db.scalar(
        select(Product)
        .join(ProductTag, ProductTag.product_id == Product.id)
        .where(
            ProductTag.nfc_tag_id == payload.tag_id,
            Product.is_active.is_(True),
        )
    )
    if product is None:
        logger.info("Scan for unregistered tag: %s", payload.tag_id)
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No active product for tag '{payload.tag_id}'"
        )

    result = ScanResult(tag_id=payload.tag_id, product=ProductOut.model_validate(product))
    await manager.broadcast({"event": "scan", **result.model_dump(mode="json")})
    return result


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            # Frontend only listens; reads keep the connection alive
            # and let us detect disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
