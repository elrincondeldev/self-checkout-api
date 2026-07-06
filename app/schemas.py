from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import TransactionStatus


# --- Products ---

class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    category: str | None = Field(default=None, max_length=60)
    size: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=40)
    price: Decimal = Field(gt=0, decimal_places=2)
    stock: int = Field(ge=0, default=0)
    is_active: bool = True


class ProductCreate(ProductBase):
    # Optional first sticker to register along with the product;
    # add more units later via POST /products/{id}/tags
    nfc_tag_id: str | None = Field(default=None, min_length=1, max_length=64)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    category: str | None = Field(default=None, max_length=60)
    size: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=40)
    price: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    stock: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nfc_tag_ids: list[str]
    created_at: datetime
    updated_at: datetime


# --- Tags (physical NFC stickers) ---

class TagCreate(BaseModel):
    nfc_tag_id: str = Field(min_length=1, max_length=64)


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nfc_tag_id: str
    product_id: int
    created_at: datetime


# --- Scan ---

class ScanRequest(BaseModel):
    tag_id: str = Field(min_length=1, max_length=64)


class ScanResult(BaseModel):
    tag_id: str
    product: ProductOut


# --- Checkout / transactions ---

class CheckoutItem(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)


class CheckoutRequest(BaseModel):
    items: list[CheckoutItem] = Field(min_length=1)


class TransactionItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    total: Decimal
    status: TransactionStatus
    created_at: datetime
    items: list[TransactionItemOut]
