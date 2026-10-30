from datetime import date

from fastapi.testclient import TestClient

from function_app import fastapi_app
from src.api.orders import summarize_order_process
from src.services.cbp_order_list_service import CbpOrderListService, _vendor_alias


class FakeSettings:
    cbp_detail_concurrency = 2
    cbp_from_date = "10-22-2025"
    cbp_to_date = "10-23-2026"


class FakeRepository:
    def __init__(self, existing: set[str] | None = None, item_codes: list[str] | None = None) -> None:
        self.existing = existing or set()
        self.item_codes = ["CHV245050DXLCDRUM"] if item_codes is None else item_codes
        self.inserted: list[tuple[dict, list]] = []

    def existing_commerce_order_ids(self, commerce_order_ids: list[str]) -> set[str]:
        return self.existing.intersection(commerce_order_ids)

    def lookup_chevron_buyback(self, customer_account_no: str):
        assert customer_account_no == "8409425"
        return [("00", "0004552", "1001")]

    def lookup_ship_to(self, customer_no: str, ship_to_code: str):
        assert (customer_no, ship_to_code) == ("0004552", "1001")
        return "NV CLK", "L72"

    def lookup_item_codes(self, vendor_alias: str) -> list[str]:
        assert vendor_alias == "227077/982"
        return self.item_codes

    def insert_listed_order(self, header: dict, items: list) -> int:
        self.inserted.append((header, items))
        return len(self.inserted)


def _detail(commerce_id: str = "06820103") -> dict:
    return {
        "commerceOrderId": commerce_id,
        "sapOrderId": "0263765303",
        "orderSource": "ECOMMERCE",
        "poNumber": "17P-00021770",
        "status": "UNACKNOWLEDGED",
        "orderDate": "06-05-2026",
        "requestedDeliveryDate": "06-12-2026",
        "customerAccountNumber": "8409272",
        "customerLocation": {"customerNumber": "8409425", "customerName": "KNIGHT"},
        "consignments": [
            {
                "code": f"{commerce_id}_DELIVERY_1",
                "entries": [
                    {
                        "code": "227077982",
                        "orderedQty": 2,
                        "unit": "DR",
                        "entryNumber": "1",
                    }
                ],
            }
        ],
    }


def _service(repository: FakeRepository) -> CbpOrderListService:
    service = CbpOrderListService(settings=FakeSettings(), repository=repository)
    service.list_orders = lambda *_args: {
        "orderList": [
            {"commerceOrderId": "06820103"},
            {"commerceOrderId": "06820104"},
            {"commerceOrderId": "06820103"},
        ]
    }
    service.get_order = lambda _site, commerce_id: _detail(commerce_id)
    return service


def test_vendor_alias_inserts_slash_after_six_digits():
    assert _vendor_alias("227077982") == "227077/982"


def test_list_orders_skips_ids_already_stored_and_saves_new_detail():
    repository = FakeRepository(existing={"06820104"})
    result = _service(repository).import_orders(
        "UNACKNOWLEDGED", "businessPoint_NA", "10-22-2025", "10-23-2026"
    )

    assert result["listed"] == 2
    assert result["alreadyStored"] == 1
    assert result["stored"] == 1
    assert result["failed"] == 0
    header, items = repository.inserted[0]
    assert header["CBPCommerceOrderId"] == "06820103"
    assert header["CustomerNo"] == "0004552"
    assert header["ShipToCode"] == "1001"
    assert header["ARDivisionNo"] == "00"
    assert header["TaxSchedule"] == "NV CLK"
    assert header["ShipExpireDate"] == date(2026, 6, 12)
    assert header.get("OrderStatus") is None
    assert items[0]["ItemCode"] == "CHV245050DXLCDRUM"
    assert items[0]["WarehouseCode"] == "L72"
    assert items[0]["CBPOrderedQty"] == 2


def test_list_orders_marks_failed_when_item_code_matches_more_than_once():
    repository = FakeRepository(item_codes=["ITEM-A", "ITEM-B"])

    result = _service(repository).import_orders(
        "UNACKNOWLEDGED", "businessPoint_NA", "10-22-2025", "10-23-2026"
    )

    assert result["stored"] == 2
    assert result["orderStatusFailed"] == 2
    assert all(header["OrderStatus"] == "FAILED" for header, _items in repository.inserted)
    assert all(
        header["ErrorDescription"] == "ItemCode exists more than 1."
        for header, _items in repository.inserted
    )
    assert all(item.get("ItemCode") is None for _header, items in repository.inserted for item in items)


def test_summary_counts_lookup_failures_and_rosetta_results():
    summary = summarize_order_process(
        {"stored": 11, "orderStatusFailed": 9, "failed": 0},
        {"processed": 2, "succeeded": 1, "failed": 1},
    )

    assert summary == {
        "processed": 11,
        "succeeded": 1,
        "failed": 10,
        "rosettaProcessed": 2,
        "rosettaSucceeded": 1,
        "rosettaFailed": 1,
    }


def test_order_process_lists_then_creates(monkeypatch):
    class FakeListService:
        def import_orders(self, status, base_site_id, from_date, to_date):
            assert (status, base_site_id, from_date, to_date) == (
                "UNACKNOWLEDGED",
                "businessPoint_NA",
                "10-22-2025",
                "10-23-2026",
            )
            return {
                "listed": 1,
                "alreadyStored": 0,
                "stored": 1,
                "orderStatusFailed": 0,
                "failed": 0,
            }

    class FakeOrderService:
        def process_unacknowledged_batch(self):
            return {"processed": 1, "succeeded": 1, "failed": 0}

    monkeypatch.setattr("src.api.orders.CbpOrderListService", FakeListService)
    monkeypatch.setattr("src.api.orders.OrderService", FakeOrderService)
    monkeypatch.setattr("src.api.orders.get_settings", lambda: FakeSettings())

    response = TestClient(fastapi_app).post("/orders/orderProcess")

    assert response.status_code == 200
    assert response.json() == {
        "list": {
            "listed": 1,
            "alreadyStored": 0,
            "stored": 1,
            "orderStatusFailed": 0,
            "failed": 0,
        },
        "create": {"processed": 1, "succeeded": 1, "failed": 0},
        "summary": {
            "processed": 1,
            "succeeded": 1,
            "failed": 0,
            "rosettaProcessed": 1,
            "rosettaSucceeded": 1,
            "rosettaFailed": 0,
        },
    }
