import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient


def payment_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "tariff_id": "standard",
        "email": "student@example.com",
        "method": "card",
    }
    body.update(overrides)
    return body


def test_tariffs_are_seeded(client: TestClient) -> None:
    response = client.get("/tariffs")
    assert response.status_code == 200
    assert response.json() == [
        {"id": "basic", "title": "Basic", "price": 990000},
        {"id": "standard", "title": "Standard", "price": 1990000},
        {"id": "premium", "title": "Premium", "price": 2990000},
    ]


@pytest.mark.parametrize(
    ("promo", "amount", "discount"),
    [(None, 1990000, 0), ("KVITTO10", 1791000, 199000), ("kvitto10", 1791000, 199000)],
)
def test_payment_amounts(
    client: TestClient, promo: str | None, amount: int, discount: int
) -> None:
    body = payment_body()
    if promo is not None:
        body["promo_code"] = promo
    response = client.post("/payments", json=body)
    assert response.status_code == 201
    payment = response.json()
    assert payment["amount"] == amount
    assert payment["discount"] == discount
    assert payment["status"] == "pending"
    assert payment["schedule"] is None
    assert payment["created_at"]
    assert client.get(f"/payments/{payment['id']}").json() == payment


@pytest.mark.parametrize("months", [3, 6, 12])
def test_installment_schedule_exact(client: TestClient, months: int) -> None:
    response = client.post(
        "/payments",
        json=payment_body(method="installment", installment_months=months),
    )
    assert response.status_code == 201
    payment = response.json()
    schedule = payment["schedule"]
    assert len(schedule) == months
    assert sum(schedule) == payment["amount"] == 1990000
    assert max(schedule) - min(schedule) <= 1
    assert schedule == sorted(schedule, reverse=True)
    if months == 3:
        assert schedule == [663334, 663333, 663333]


def test_idempotency_returns_same_payment_without_duplicate(client: TestClient) -> None:
    headers = {"Idempotency-Key": "checkout-123"}
    first = client.post("/payments", json=payment_body(), headers=headers)
    replay = client.post(
        "/payments", json=payment_body(tariff_id="premium"), headers=headers
    )
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert len(client.get("/payments").json()) == 1


def test_discounted_installments_use_final_amount(client: TestClient) -> None:
    response = client.post(
        "/payments",
        json=payment_body(
            method="installment", installment_months=12, promo_code="kvitto10"
        ),
    )
    assert response.status_code == 201
    payment = response.json()
    assert payment["discount"] == 199000
    assert payment["amount"] == 1791000
    assert sum(payment["schedule"]) == payment["amount"]


def test_invalid_transition_does_not_change_status(client: TestClient) -> None:
    payment_id = client.post("/payments", json=payment_body()).json()["id"]
    response = client.post(
        "/webhooks/bank", json={"payment_id": payment_id, "status": "refunded"}
    )
    assert response.status_code == 409
    assert response.json() == {"error": "invalid_transition"}
    assert client.get(f"/payments/{payment_id}").json()["status"] == "pending"


def test_valid_transitions_and_terminal_status(client: TestClient) -> None:
    payment_id = client.post("/payments", json=payment_body()).json()["id"]
    for status in ("succeeded", "refunded"):
        response = client.post(
            "/webhooks/bank", json={"payment_id": payment_id, "status": status}
        )
        assert response.status_code == 200
        assert response.json() == {"result": "ok"}
        assert client.get(f"/payments/{payment_id}").json()["status"] == status
    repeated = client.post(
        "/webhooks/bank", json={"payment_id": payment_id, "status": "refunded"}
    )
    assert repeated.status_code == 409


def test_failed_payment_cannot_succeed_later(client: TestClient) -> None:
    payment_id = client.post("/payments", json=payment_body()).json()["id"]
    failed = client.post(
        "/webhooks/bank", json={"payment_id": payment_id, "status": "failed"}
    )
    assert failed.status_code == 200
    invalid = client.post(
        "/webhooks/bank", json={"payment_id": payment_id, "status": "succeeded"}
    )
    assert invalid.status_code == 409
    assert client.get(f"/payments/{payment_id}").json()["status"] == "failed"


def test_missing_payment_returns_404(client: TestClient) -> None:
    assert client.get("/payments/999").status_code == 404
    assert (
        client.post(
            "/webhooks/bank", json={"payment_id": 999, "status": "failed"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "body",
    [
        payment_body(promo_code="OTHER"),
        payment_body(tariff_id="unknown"),
        payment_body(method="installment"),
        payment_body(method="installment", installment_months=4),
        payment_body(method="card", installment_months=3),
        payment_body(method="cash"),
    ],
)
def test_bad_payment_request_returns_422(
    client: TestClient, body: dict[str, object]
) -> None:
    response = client.post("/payments", json=body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_payment_filters(client: TestClient) -> None:
    first = client.post("/payments", json=payment_body()).json()
    client.post("/payments", json=payment_body(email="other@example.com", method="sbp"))
    client.post(
        "/webhooks/bank", json={"payment_id": first["id"], "status": "succeeded"}
    )
    by_email = client.get("/payments", params={"email": "student@example.com"})
    by_status = client.get("/payments", params={"status": "succeeded"})
    assert [item["id"] for item in by_email.json()] == [first["id"]]
    assert [item["id"] for item in by_status.json()] == [first["id"]]


def test_email_filter_validates_and_normalizes_domain(client: TestClient) -> None:
    payment = client.post(
        "/payments", json=payment_body(email="Student@Example.COM")
    ).json()
    assert payment["email"] == "Student@example.com"

    match = client.get("/payments", params={"email": "Student@EXAMPLE.COM"})
    assert match.status_code == 200
    assert match.json() == [payment]

    missing = client.get("/payments", params={"email": "other@example.com"})
    assert missing.status_code == 200
    assert missing.json() == []

    invalid = client.get("/payments", params={"email": "1"})
    assert invalid.status_code == 422
    assert invalid.json()["detail"][0]["loc"] == ["query", "email"]


def test_webhook_signature(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")
    payment_id = client.post("/payments", json=payment_body()).json()["id"]
    body = json.dumps(
        {"payment_id": payment_id, "status": "succeeded"}, indent=2
    ).encode()
    invalid = client.post(
        "/webhooks/bank",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": "bad"},
    )
    assert invalid.status_code == 401
    assert client.get(f"/payments/{payment_id}").json()["status"] == "pending"
    signature = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    valid = client.post(
        "/webhooks/bank",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )
    assert valid.status_code == 200
    assert client.get(f"/payments/{payment_id}").json()["status"] == "succeeded"


def test_swagger_and_openapi_are_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
