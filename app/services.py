from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Payment, Tariff
from .schemas import PaymentCreate, PaymentStatus

ALLOWED_TRANSITIONS = {
    "pending": {"succeeded", "failed"},
    "succeeded": {"refunded"},
    "failed": set(),
    "refunded": set(),
}


def installment_schedule(amount: int, months: int) -> list[int]:
    base, extra = divmod(amount, months)
    return [base + (index < extra) for index in range(months)]


def create_payment(
    db: Session, payload: PaymentCreate, idempotency_key: str | None
) -> tuple[Payment, bool]:
    if idempotency_key is not None:
        existing = db.scalar(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing, False

    tariff = db.get(Tariff, payload.tariff_id)
    if tariff is None:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "type": "value_error",
                    "loc": ["body", "tariff_id"],
                    "msg": "Unknown tariff",
                    "input": payload.tariff_id,
                }
            ],
        )

    discount = tariff.price // 10 if payload.promo_code else 0
    amount = tariff.price - discount
    schedule = (
        installment_schedule(amount, payload.installment_months)
        if payload.installment_months is not None
        else None
    )
    payment = Payment(
        tariff_id=tariff.id,
        email=str(payload.email),
        method=payload.method,
        installment_months=payload.installment_months,
        schedule=schedule,
        amount=amount,
        discount=discount,
        status="pending",
        idempotency_key=idempotency_key,
    )
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if idempotency_key is not None:
            existing = db.scalar(
                select(Payment).where(Payment.idempotency_key == idempotency_key)
            )
            if existing is not None:
                return existing, False
        raise
    return payment, True


def transition_payment(db: Session, payment_id: int, new_status: PaymentStatus) -> bool:
    with db.begin():
        payment = db.scalar(
            select(Payment).where(Payment.id == payment_id).with_for_update()
        )
        if payment is None:
            raise HTTPException(status_code=404, detail="Payment not found")
        if new_status not in ALLOWED_TRANSITIONS[payment.status]:
            return False
        payment.status = new_status
    return True
