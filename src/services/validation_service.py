from src.schemas.order import RosettaOrder


class ValidationService:
    def validate_order(self, order: RosettaOrder) -> None:
        errors: list[str] = []
        has_customer_id = bool(order.customer_id)
        # has_dm2_customer = bool(order.ar_division_no and order.customer_no)

        # if not (has_customer_id or has_dm2_customer):
        #     errors.append("Provide CustomerID or both ARDivisionNo and CustomerNo.")

        for item in order.items:
            if not item.item_code and not item.product_id:
                errors.append(
                    f"Order item {item.order_item_id}: ItemCode or ProductID mapping is required."
                )
            if item.order_quantity <= 0:
                errors.append(
                    f"Order item {item.order_item_id}: CBPOrderedQty must be greater than zero."
                )

        if errors:
            raise ValueError(" ".join(errors))