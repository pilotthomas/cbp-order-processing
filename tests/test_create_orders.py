from decimal import Decimal

from src.core.config import Settings, get_pyodbc_connection_string, reset_credentials
from src.schemas.order import OrderItem, RosettaOrder
from src.services.order_service import OrderService


class FakeSettings:
    batch_size = 5
    rosetta_host = "10.101.3.27"
    rosetta_port = 55555
    rosetta_timeout_seconds = 30.0


class FakeRepository:
    def __init__(self, orders: dict[int, RosettaOrder | None]) -> None:
        self.orders = orders
        self.updates: list[tuple] = []
        self.error_only: list[tuple] = []

    def get_unacknowledged_order_ids(self, batch_size: int) -> list[int]:
        return list(self.orders)[:batch_size]

    def get_order_for_rosetta(self, order_id: int) -> RosettaOrder | None:
        return self.orders.get(order_id)

    def update_rosetta_result(self, order_id, status, error_description=None, sales_order_no=None, **_kwargs):
        self.updates.append((order_id, status, error_description, sales_order_no))

    def update_error_description(self, order_id, error_description):
        self.error_only.append((order_id, error_description))


class FakeRosetta:
    def __init__(self, response: bytes | Exception) -> None:
        self.host = "10.101.3.27"
        self.port = 55555
        self.response = response
        self.sent: list[bytes] = []

    def exchange(self, xml_payload: bytes) -> bytes:
        self.sent.append(xml_payload)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _order(order_id: int = 2) -> RosettaOrder:
    return RosettaOrder(
        order_id=order_id,
        customer_no="0004552",
        ar_division_no="00",
        ship_to_code="1001",
        order_date="20260605",
        customer_po_no="17P-00021770",
        items=[
            OrderItem(
                order_item_id=1,
                product_code="227077982",
                item_code="CHV245050DXLCDRUM",
                order_quantity=Decimal("2"),
                warehouse_code="L72",
                unit="DR",
            )
        ],
    )


def _service(orders, response) -> tuple[OrderService, FakeRepository, FakeRosetta]:
    repository = FakeRepository(orders)
    client = FakeRosetta(response)
    service = OrderService(
        repository=repository,
        settings=FakeSettings(),
        xml_builder=type("Builder", (), {"build": staticmethod(lambda _order: b"<rosetta/>")})(),
        rosetta_client=client,
    )
    return service, repository, client


def test_create_order_marks_success_and_stores_sales_order_no():
    service, repository, client = _service(
        {2: _order()},
        b"<rosetta><ErrorStatus>0</ErrorStatus><SalesOrderNo>1613495</SalesOrderNo></rosetta>",
    )

    result = service.submit_order(2)

    assert result["success"] is True
    assert result["sales_order_no"] == "1613495"
    assert repository.updates == [(2, "SUCCESS", None, "1613495")]
    assert repository.error_only == []
    assert client.sent == [b"<rosetta/>"]


def test_create_order_already_exists_updates_error_only():
    service, repository, _client = _service(
        {2: _order()},
        b"<rosetta><ErrorStatus>1</ErrorStatus><ErrorMessage>SY040_DM2Rosetta : Order already exists</ErrorMessage></rosetta>",
    )

    result = service.submit_order(2)

    assert result["success"] is False
    assert repository.updates == []
    assert repository.error_only == [(2, "SY040_DM2Rosetta : Order already exists")]


def test_create_order_timeout_is_stored_as_failed():
    service, repository, _client = _service({3: _order(3)}, TimeoutError("timed out"))

    result = service.submit_order(3)

    assert result == {
        "success": False,
        "order_id": 3,
        "message": "TimeoutError: timed out",
    }
    assert repository.updates == [(3, "FAILED", "TimeoutError: timed out", None)]


def test_create_order_missing_row_does_not_call_rosetta():
    service, repository, client = _service({9: None}, b"")

    result = service.submit_order(9)

    assert result["message"] == "Order was not found in CBPOrders."
    assert client.sent == []
    assert repository.updates == []


def test_rosetta_settings_come_from_environment(monkeypatch):
    monkeypatch.setenv("KEY_VAULT_URL", "https://example.vault.azure.net/")
    monkeypatch.setenv("ROSETTA_HOST", "10.101.3.27")
    monkeypatch.setenv("ROSETTA_PORT", "55555")
    monkeypatch.setenv("ROSETTA_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("ROSETTA_FUNCTION", "CreateOrder")
    monkeypatch.setenv("ROSETTA_SECURITY_KEY", "from-env")
    monkeypatch.setattr(
        "src.core.config.get_secret",
        lambda name: (_ for _ in ()).throw(AssertionError(name)),
    )

    settings = Settings()

    assert settings.rosetta_host == "10.101.3.27"
    assert settings.rosetta_port == 55555
    assert settings.rosetta_timeout_seconds == 30.0
    assert settings.rosetta_function == "CreateOrder"
    assert settings.rosetta_security_key == "from-env"


def test_blank_settings_use_key_vault_secret_names(monkeypatch):
    reset_credentials()
    monkeypatch.setenv("KEY_VAULT_URL", "https://example.vault.azure.net/")
    for name in (
        "ROSETTA_HOST",
        "ROSETTA_PORT",
        "ROSETTA_TIMEOUT_SECONDS",
        "ROSETTA_FUNCTION",
        "ROSETTA_SECURITY_KEY",
        "CBP_CLIENT_ID",
        "CBP_CLIENT_SECRET",
        "CBP_RESOURCE",
        "CBP_SUBSCRIPTION_KEY",
        "DB_HOST",
        "DB_NAME",
        "DB_ODBC_DRIVER",
        "DB_TRUSTED_CONNECTION",
        "DB_TRUST_SERVER_CERTIFICATE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DB_USER", "svc-user")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    secrets = {
        "cbp-rosetta-api-host": "10.0.0.5",
        "cbp-rosetta-api-port": "55555",
        "cbp-rosetta-timeout-seconds": "30",
        "cbp-rosetta-function-create": "CreateOrder",
        "cbp-rosetta-api-security-key": "vault-key",
        "cbp-client-id": "client-id",
        "cbp-client-secret": "client-secret",
        "cbp-resource": "resource-id",
        "cbp-subscription-key": "subscription-key",
        "cbp-db-hostname": "sql.example",
        "cbp-db-name": "MAS_PTL",
        "cbp-odbc-driver": "ODBC Driver 18 for SQL Server",
        "cbp-db-trusted-connection": "no",
        "cbp-trust-server-certificate": "yes",
    }
    monkeypatch.setattr("src.core.config.get_secret", lambda name: secrets[name])

    settings = Settings()

    assert settings.rosetta_host == "10.0.0.5"
    assert settings.rosetta_port == 55555
    assert settings.rosetta_timeout_seconds == 30.0
    assert settings.rosetta_function == "CreateOrder"
    assert settings.rosetta_security_key == "vault-key"
    assert settings.cbp_client_id == "client-id"
    assert settings.cbp_client_secret == "client-secret"
    assert settings.cbp_resource == "resource-id"
    assert settings.cbp_subscription_key == "subscription-key"
    connection = get_pyodbc_connection_string()
    assert "SERVER=sql.example" in connection
    assert "DATABASE=MAS_PTL" in connection
    assert "DRIVER={ODBC Driver 18 for SQL Server}" in connection
    assert "TrustServerCertificate=yes" in connection
    assert "Trusted_Connection" not in connection
    reset_credentials()


def test_blank_batch_size_selects_every_eligible_order(monkeypatch):
    monkeypatch.delenv("BATCH_SIZE", raising=False)
    assert Settings().batch_size is None


def test_batch_size_limits_the_run(monkeypatch):
    monkeypatch.setenv("BATCH_SIZE", "5")
    assert Settings().batch_size == 5


def test_create_order_batch_counts_success_and_failure():
    service, _repository, _client = _service(
        {2: _order(2), 3: _order(3)},
        b"<rosetta><ErrorStatus>0</ErrorStatus><SalesOrderNo>1613495</SalesOrderNo></rosetta>",
    )
    service.rosetta_client.exchange = lambda payload: (
        b"<rosetta><ErrorStatus>1</ErrorStatus><ErrorMessage>inactive item</ErrorMessage></rosetta>"
        if service.repository.updates or service.repository.error_only
        else b"<rosetta><ErrorStatus>0</ErrorStatus><SalesOrderNo>1613495</SalesOrderNo></rosetta>"
    )

    summary = service.process_unacknowledged_batch()

    assert summary == {"processed": 2, "succeeded": 1, "failed": 1}
