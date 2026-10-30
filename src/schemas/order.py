from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class OrderItem(BaseModel):
    order_item_id: int
    product_code: str
    product_id: str | None = None
    item_code: str | None = None
    order_quantity: Decimal = Field(gt=0)
    warehouse_code: str | None = Field(default=None, max_length=3)
    unit: str | None = None

    @field_validator(
        "product_code",
        "product_id",
        "item_code",
        "warehouse_code",
        "unit",
        mode="before",
    )
    @classmethod
    def strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

class RosettaOrder(BaseModel):
    order_id: int
    external_source_id: str | None = None
    sales_order_no: str | None = None
    order_type: str = "S"
    ar_division_no: str | None = None
    customer_no: str | None = None
    customer_id: str | None = None
    destination_id: str | None = None
    ship_to_code: str | None = Field(default=None, max_length=4)
    order_date: str | None = None
    ship_expire_date: str | None = None
    tax_schedule: str | None = None
    ticket_class: str | None = None
    customer_po_no: str | None = None
    items: list[OrderItem] = Field(min_length=1)

    @field_validator(
        "ship_to_code",
        "tax_schedule",
        "ticket_class",
        "customer_po_no",
        mode="before",
    )
    @classmethod
    def strip_optional_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value