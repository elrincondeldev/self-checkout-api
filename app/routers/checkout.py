from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Product, Transaction, TransactionItem
from app.schemas import CheckoutRequest, TransactionOut

router = APIRouter(tags=["checkout"])


@router.post("/checkout", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def checkout(payload: CheckoutRequest, db: Session = Depends(get_db)) -> Transaction:
    # Merge duplicate product lines (same product scanned as separate entries)
    quantities: dict[int, int] = defaultdict(int)
    for item in payload.items:
        quantities[item.product_id] += item.quantity

    # Lock the product rows so concurrent checkouts can't oversell stock
    products = {
        p.id: p
        for p in db.scalars(
            select(Product).where(Product.id.in_(quantities)).with_for_update()
        )
    }

    errors: list[str] = []
    for product_id, quantity in quantities.items():
        product = products.get(product_id)
        if product is None or not product.is_active:
            errors.append(f"Product {product_id} not found or inactive")
        elif product.stock < quantity:
            errors.append(
                f"Insufficient stock for '{product.name}': have {product.stock}, need {quantity}"
            )
    if errors:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "; ".join(errors))

    transaction = Transaction(total=Decimal("0.00"))
    total = Decimal("0.00")
    for product_id, quantity in quantities.items():
        product = products[product_id]
        subtotal = product.price * quantity
        total += subtotal
        product.stock -= quantity
        transaction.items.append(
            TransactionItem(
                product_id=product_id,
                quantity=quantity,
                unit_price=product.price,
                subtotal=subtotal,
            )
        )
    transaction.total = total

    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(
    db: Session = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> list[Transaction]:
    query = (
        select(Transaction)
        .order_by(Transaction.created_at.desc())
        .limit(min(max(limit, 1), 200))
        .offset(max(offset, 0))
    )
    return list(db.scalars(query))


@router.get("/transactions/{transaction_id}", response_model=TransactionOut)
def get_transaction(transaction_id: int, db: Session = Depends(get_db)) -> Transaction:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return transaction
