from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.ais import OrderInput, UserInput, UserSettingsInput, next_sim_order_id_start
from app.ais import app as ais_app
from app.main import OrderEvent
from app.main import app as balancer_app


def test_case_order_maps_sum_and_source_timestamp() -> None:
    event = OrderEvent.model_validate(
        {
            "id": 17,
            "user_id": 4,
            "sum": 12000,
            "order_type": "ORDER_1",
            "subject": "subject-a",
            "source_updated_at": "2026-01-02T03:04:05Z",
        }
    )
    assert event.sum == 12000
    assert event.user_id == 4
    assert event.source_updated_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_ais_payload_validates_source_entities() -> None:
    user = UserInput(id=4, first_name="А", last_name="Б", status="inactive")
    order = OrderInput(
        id=17, amount=12000, order_type="ORDER_1", subject="subject-a", status="await"
    )
    assert user.status == "inactive"
    assert order.amount == 12000
    assert (
        UserSettingsInput(user_id=4, settings={"max_daily_limit": 10}).settings["max_daily_limit"]
        == 10
    )


def test_user_settings_reject_negative_limit() -> None:
    import pytest

    with pytest.raises(ValueError):
        UserSettingsInput(user_id=4, settings={"max_daily_limit": -1})


def test_simulator_resumes_ids_after_existing_orders() -> None:
    assert next_sim_order_id_start(None) == 2_026_000_000
    assert next_sim_order_id_start(2_026_000_123) == 2_026_000_124
    assert next_sim_order_id_start(1_790_610_159_315) == 1_790_610_159_316


def test_health_and_docs_routes_are_registered() -> None:
    with TestClient(balancer_app) as balancer, TestClient(ais_app) as ais:
        assert balancer.get("/health").json() == {"status": "ok"}
        assert ais.get("/health").json() == {"status": "ok"}
        assert "/ingest/orders" in balancer.get("/openapi.json").json()["paths"]
        assert "/api/assignments" in ais.get("/openapi.json").json()["paths"]
        paths = ais.get("/openapi.json").json()["paths"]
        assert "/api/user-settings" in paths
        assert "/api/user-settings/{user_id}" in paths
        assert "/api/orders/{order_id}/status" in paths
        assert balancer.get("/api/parameters").status_code == 401
