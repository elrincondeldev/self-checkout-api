from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product, ProductTag
from app.schemas import ProductCreate, ProductOut, ProductUpdate, TagCreate, TagOut

router = APIRouter(prefix="/products", tags=["products"])


def get_product_or_404(product_id: int, db: Session) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


def ensure_tag_free(nfc_tag_id: str, db: Session) -> None:
    existing = db.scalar(select(ProductTag).where(ProductTag.nfc_tag_id == nfc_tag_id))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"NFC tag '{nfc_tag_id}' is already assigned to product {existing.product_id}",
        )


@router.get("", response_model=list[ProductOut])
def list_products(
    db: Session = Depends(get_db),
    include_inactive: bool = Query(False, description="Also return soft-deleted products"),
    category: str | None = Query(None, description="Filter by category"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[Product]:
    query = select(Product).order_by(Product.id).limit(limit).offset(offset)
    if not include_inactive:
        query = query.where(Product.is_active.is_(True))
    if category:
        query = query.where(Product.category == category)
    return list(db.scalars(query))


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)) -> Product:
    return get_product_or_404(product_id, db)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)) -> Product:
    data = payload.model_dump()
    first_tag = data.pop("nfc_tag_id", None)
    if first_tag:
        ensure_tag_free(first_tag, db)
    product = Product(**data)
    if first_tag:
        product.tags.append(ProductTag(nfc_tag_id=first_tag))
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)
) -> Product:
    product = get_product_or_404(product_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", response_model=ProductOut)
def delete_product(product_id: int, db: Session = Depends(get_db)) -> Product:
    product = get_product_or_404(product_id, db)
    product.is_active = False
    db.commit()
    db.refresh(product)
    return product


# --- Tags: one row per physical sticker, many stickers per product ---

@router.get("/{product_id}/tags", response_model=list[TagOut])
def list_tags(product_id: int, db: Session = Depends(get_db)) -> list[ProductTag]:
    product = get_product_or_404(product_id, db)
    return product.tags


@router.post("/{product_id}/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def add_tag(product_id: int, payload: TagCreate, db: Session = Depends(get_db)) -> ProductTag:
    product = get_product_or_404(product_id, db)
    ensure_tag_free(payload.nfc_tag_id, db)
    tag = ProductTag(nfc_tag_id=payload.nfc_tag_id, product=product)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/{product_id}/tags/{nfc_tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_tag(product_id: int, nfc_tag_id: str, db: Session = Depends(get_db)) -> None:
    tag = db.scalar(
        select(ProductTag).where(
            ProductTag.product_id == product_id,
            ProductTag.nfc_tag_id == nfc_tag_id,
        )
    )
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found on this product")
    db.delete(tag)
    db.commit()
