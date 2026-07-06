import logging
from collections import deque
from datetime import datetime, timezone

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

# Rolling log of the latest scans (known and unknown), newest first.
# In-memory on purpose: it's an operator aid, not business data.
_recent_scans: deque[dict] = deque(maxlen=50)


def _remember_scan(tag_id: str, product: Product | None) -> None:
    _recent_scans.appendleft(
        {
            "tag_id": tag_id,
            "known": product is not None,
            "product_id": product.id if product else None,
            "product_name": product.name if product else None,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
    )


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
    _remember_scan(payload.tag_id, product)
    if product is None:
        logger.info("Scan for unregistered tag: %s", payload.tag_id)
        await manager.broadcast({"event": "unknown_tag", "tag_id": payload.tag_id})
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No active product for tag '{payload.tag_id}'"
        )

    result = ScanResult(tag_id=payload.tag_id, product=ProductOut.model_validate(product))
    await manager.broadcast({"event": "scan", **result.model_dump(mode="json")})
    return result


@router.get("/scans/recent")
def recent_scans() -> list[dict]:
    """Latest scans (max 50, newest first) — operator aid for registering
    new garments: scan the sticker, read its UID here, create the product."""
    return list(_recent_scans)


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
