from src.core.config import Settings, get_settings
from src.core.logger import log_exception, logger
from src.db.order_repository import OrderRepository
from src.db.status_repository import StatusRepository
from src.schemas.order import RosettaOrder
from src.services.rosetta_response_parser import RosettaResponseParser
from src.services.rosetta_socket_client import RosettaSocketClient
from src.services.rosetta_xml_builder import RosettaXmlBuilder
from src.services.validation_service import ValidationService


class OrderService:
    def __init__(
        self,
        repository: OrderRepository | None = None,
        settings: Settings | None = None,
        validation_service: ValidationService | None = None,
        xml_builder: RosettaXmlBuilder | None = None,
        rosetta_client: RosettaSocketClient | None = None,
    ) -> None:
        self.repository = repository or OrderRepository()
        self.settings = settings or get_settings()
        self.validation_service = validation_service or ValidationService()
        self.xml_builder = xml_builder or RosettaXmlBuilder(self.settings)
        self.rosetta_client = rosetta_client

    def process_unacknowledged_batch(self, batch_size: int | None = None) -> dict:
        size = self.settings.batch_size if batch_size is None else batch_size
        order_ids = self.repository.get_unacknowledged_order_ids(size)
        results = [self.submit_order(order_id) for order_id in order_ids]
        succeeded = sum(result["success"] for result in results)
        return {
            "processed": len(results),
            "succeeded": succeeded,
            "failed": len(results) - succeeded,
        }

    def submit_order(self, order_id: int) -> dict:
        order: RosettaOrder | None = None
        request_xml: str | None = None
        response_xml: str | None = None
        try:
            order = self.repository.get_order_for_rosetta(order_id)
            logger.info("Retrieved CBP order CBPOrderId=%s", order_id)
            if order is None:
                return {
                    "success": False,
                    "order_id": order_id,
                    "message": "Order was not found in CBPOrders.",
                }

            self.validation_service.validate_order(order)
            if not self.settings.rosetta_host or self.settings.rosetta_port <= 0:
                raise RuntimeError("Rosetta host and port are not configured.")

            xml_payload = self.xml_builder.build(order)
            request_xml = xml_payload.decode("utf-8")
            client = self.rosetta_client or RosettaSocketClient(
                self.settings.rosetta_host,
                self.settings.rosetta_port,
                self.settings.rosetta_timeout_seconds,
            )
            logger.info(
                "Sending order to Rosetta host=%s port=%s CBPOrderId=%s",
                client.host,
                client.port,
                order_id,
            )
            raw_response = client.exchange(xml_payload)
            response_xml = raw_response.decode("utf-8", errors="replace")
            response = RosettaResponseParser().parse(raw_response)
            result = response.model_dump()
            if _order_already_exists(response.error_message) or _order_already_exists(
                response_xml
            ):
                StatusRepository(self.repository).update_error_description(
                    order_id,
                    response.error_message,
                )
                logger.info(
                    "Order already exists CBPOrderId=%s; updated ErrorDescription only",
                    order_id,
                )
                return {
                    "success": False,
                    "order_id": order_id,
                    "message": response.error_message,
                    "rosetta_response": result,
                }
            sales_order_no = (
                response.order.get("sales_order_no") if response.order else None
            )
            status = "SUCCESS" if response.success else "FAILED"
            StatusRepository(self.repository).update(
                order_id,
                status,
                response.error_message,
                sales_order_no if response.success else None,
                request_xml=request_xml,
                response_xml=response_xml,
            )
            logger.info(
                "Rosetta result CBPOrderId=%s status=%s sales_order_no=%s",
                order_id,
                status,
                sales_order_no,
            )
            return {
                "success": response.success,
                "order_id": order_id,
                "sales_order_no": sales_order_no,
                "message": response.error_message
                or "Rosetta order processed successfully.",
                "rosetta_response": result,
            }
        except Exception as error:
            log_exception(f"submit_order failed CBPOrderId={order_id}", exc=error)
            message = f"{type(error).__name__}: {error}"
            logger.error(
                "Saving Rosetta failure to CBPOrders CBPOrderId=%s OrderStatus=FAILED ErrorDescription=%s",
                order_id,
                message,
            )
            try:
                StatusRepository(self.repository).update(
                    order_id,
                    "FAILED",
                    message,
                    request_xml=request_xml,
                    response_xml=response_xml,
                )
                logger.error(
                    "Saved Rosetta failure to CBPOrders CBPOrderId=%s ErrorDescription=%s",
                    order_id,
                    message,
                )
            except Exception as update_error:
                log_exception(
                    f"Could not persist failure status CBPOrderId={order_id}",
                    exc=update_error,
                )
                raise RuntimeError(
                    f"Order processing failed: {message}. Could not persist failure status: {update_error}"
                ) from error
            return {"success": False, "order_id": order_id, "message": message}


def _order_already_exists(error_message: str | None) -> bool:
    """True when Rosetta reports the order is already in Sage."""
    if not error_message:
        return False
    return "already exist" in error_message.lower()