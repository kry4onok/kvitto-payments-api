import hashlib
import hmac
import os
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Payment, Tariff
from .schemas import PaymentCreate, PaymentRead, PaymentStatus, TariffRead, WebhookEvent
from .services import create_payment, transition_payment

app = FastAPI(title="Kvitto Payments API", version="1.0.0")

DbSession = Annotated[Session, Depends(get_db)]


@app.get("/tariffs", response_model=list[TariffRead])
def get_tariffs(db: DbSession) -> list[Tariff]:
    return list(db.scalars(select(Tariff).order_by(Tariff.price)))


@app.post("/payments", response_model=PaymentRead, status_code=201)
def post_payment(
    payload: PaymentCreate,
    response: Response,
    db: DbSession,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ] = None,
) -> Payment:
    payment, created = create_payment(db, payload, idempotency_key)
    if not created:
        response.status_code = 200
    return payment


@app.get("/payments", response_model=list[PaymentRead])
def get_payments(
    db: DbSession,
    email: EmailStr | None = None,
    status: PaymentStatus | None = None,
) -> list[Payment]:
    query = select(Payment)
    if email is not None:
        query = query.where(Payment.email == email)
    if status is not None:
        query = query.where(Payment.status == status)
    return list(db.scalars(query.order_by(Payment.id)))


@app.get("/payments/{payment_id}", response_model=PaymentRead)
def get_payment(payment_id: int, db: DbSession) -> Payment:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


async def verify_webhook_signature(
    request: Request,
    x_signature: Annotated[
        str | None,
        Header(
            alias="X-Signature",
            description="Hex HMAC-SHA256 of exact body bytes; whitespace matters.",
        ),
    ] = None,
) -> None:
    secret = os.getenv("WEBHOOK_SECRET")
    if secret:
        expected = hmac.new(
            secret.encode("utf-8"), await request.body(), hashlib.sha256
        ).hexdigest()
        if x_signature is None or not hmac.compare_digest(expected, x_signature):
            raise HTTPException(status_code=401, detail="Invalid signature")


@app.post("/webhooks/bank", response_model=None)
def bank_webhook(
    event: WebhookEvent,
    db: DbSession,
    _: Annotated[None, Depends(verify_webhook_signature)],
) -> dict[str, str] | JSONResponse:
    """Update a payment status after checking the bank signature when configured."""
    if not transition_payment(db, event.payment_id, event.status):
        return JSONResponse(status_code=409, content={"error": "invalid_transition"})
    return {"result": "ok"}


# See PyCharm help at https://www.jetbrains.com/help/pycharm/
