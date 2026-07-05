from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product
from app.schemas import ProductCreate, ProductOut, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


def get_product_or_404(product_id: int, db: Session) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


@router.get("", response_model=list[ProductOut])
def list_products(
    db: Session = Depends(get_db),
    include_inactive: bool = Query(False, description="Also return soft-deleted products"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[Product]:
    query = select(Product).order_by(Product.id).limit(limit).offset(offset)
    if not include_inactive:
        query = query.where(Product.is_active.is_(True))
    return list(db.scalars(query))


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)) -> Product:
    return get_product_or_404(product_id, db)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)) -> Product:
    existing = db.scalar(select(Product).where(Product.nfc_tag_id == payload.nfc_tag_id))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"NFC tag '{payload.nfc_tag_id}' is already assigned to product {existing.id}",
        )
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)
) -> Product:
    product = get_product_or_404(product_id, db)
    updates = payload.model_dump(exclude_unset=True)

    new_tag = updates.get("nfc_tag_id")
    if new_tag and new_tag != product.nfc_tag_id:
        existing = db.scalar(select(Product).where(Product.nfc_tag_id == new_tag))
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"NFC tag '{new_tag}' is already assigned to product {existing.id}",
            )

    for field, value in updates.items():
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
