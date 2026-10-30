from src.db.order_repository import OrderRepository


class StatusRepository:
    def __init__(self, orders: OrderRepository | None = None) -> None:
        self.orders = orders or OrderRepository()

    def update(
        self,
        order_id: int,
        status: str,
        message: str | None = None,
        sales_order_no: str | None = None,
        request_xml: str | None = None,
        response_xml: str | None = None,
    ) -> None:
        self.orders.update_rosetta_result(
            order_id=order_id,
            status=status,
            error_description=message,
            sales_order_no=sales_order_no,
            request_xml=request_xml,
            response_xml=response_xml,
        )

    def update_error_description(self, order_id: int, message: str | None = None) -> None:
        self.orders.update_error_description(order_id, message)