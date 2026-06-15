"""
Tests for restocking order API endpoints.
"""
import pytest


def _build_request(client, budget, skus=None):
    """Build a CreateRestockingOrderRequest payload from real demand forecasts.

    Pulls live forecast data so SKU/cost/quantity always match the seed data,
    optionally restricting to a subset of SKUs.
    """
    forecasts = client.get("/api/demand").json()
    if skus is not None:
        forecasts = [f for f in forecasts if f["item_sku"] in skus]
    items = [
        {
            "sku": f["item_sku"],
            "name": f["item_name"],
            "quantity": f["forecasted_demand"],
            "unit_cost": f["unit_cost"],
        }
        for f in forecasts
    ]
    return {"budget": budget, "items": items}


class TestRestockingEndpoints:
    """Test suite for restocking order endpoints."""

    def test_demand_forecast_includes_unit_cost(self, client):
        """Demand forecasts must expose unit_cost for restock cost estimation."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0
        for forecast in data:
            assert "unit_cost" in forecast
            assert isinstance(forecast["unit_cost"], (int, float))
            assert forecast["unit_cost"] > 0

    def test_get_restocking_orders_returns_list(self, client):
        """GET should always return a list."""
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_restocking_order_success(self, client):
        """A within-budget order is created and returned with computed fields."""
        payload = _build_request(client, budget=100000, skus=["WDG-001", "GSK-203"])
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 200

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-2025-")
        assert order["budget"] == 100000
        assert order["total_cost"] > 0
        assert order["total_cost"] <= order["budget"]
        assert len(order["items"]) == 2

        # Verify total_cost equals the sum of line totals (money tolerance)
        calculated = sum(item["quantity"] * item["unit_cost"] for item in order["items"])
        assert abs(order["total_cost"] - calculated) < 0.01

    def test_create_restocking_order_assigns_lead_times(self, client):
        """Each line gets a 7-21 day lead time; order lead time is the max."""
        payload = _build_request(client, budget=100000, skus=["WDG-001", "GSK-203"])
        order = client.post("/api/restocking-orders", json=payload).json()

        assert order["lead_time_days"] >= 1
        item_lead_times = []
        for item in order["items"]:
            assert "lead_time_days" in item
            assert 7 <= item["lead_time_days"] <= 21
            assert "line_total" in item
            item_lead_times.append(item["lead_time_days"])

        # Order-level lead time is the longest line's lead time
        assert order["lead_time_days"] == max(item_lead_times)
        # Expected delivery is populated
        assert order["expected_delivery"]
        assert "T" in order["expected_delivery"]

    def test_create_restocking_order_exceeds_budget(self, client):
        """An order whose total exceeds the budget is rejected with 400."""
        payload = _build_request(client, budget=100, skus=["MTR-304"])
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "budget" in data["detail"].lower()

    def test_create_restocking_order_empty_items(self, client):
        """Submitting with no items is rejected with 400."""
        response = client.post(
            "/api/restocking-orders", json={"budget": 5000, "items": []}
        )
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_restocking_order_missing_budget(self, client):
        """Missing required fields fail Pydantic validation with 422."""
        response = client.post(
            "/api/restocking-orders",
            json={"items": [{"sku": "WDG-001", "name": "Widget", "quantity": 10, "unit_cost": 5.0}]},
        )
        assert response.status_code == 422

    def test_submitted_order_appears_in_get(self, client):
        """A created order is subsequently retrievable via GET, newest first."""
        payload = _build_request(client, budget=100000, skus=["FLT-405"])
        created = client.post("/api/restocking-orders", json=payload).json()

        listed = client.get("/api/restocking-orders").json()
        assert isinstance(listed, list)
        order_numbers = [o["order_number"] for o in listed]
        assert created["order_number"] in order_numbers
        # Newest first: the just-created order should be at the front
        assert listed[0]["order_number"] == created["order_number"]
