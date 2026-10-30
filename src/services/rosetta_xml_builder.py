from xml.etree.ElementTree import Element, SubElement, tostring

from src.core.config import Settings, get_settings
from src.schemas.order import RosettaOrder


class RosettaXmlBuilder:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def build(self, order: RosettaOrder) -> bytes:
        root = Element("rosetta")
        SubElement(root, "securitykey").text = self.settings.rosetta_security_key
        SubElement(root, "function").text = self.settings.rosetta_function
        xml = SubElement(root, "xml")

        sales_order_no = SubElement(xml, "SalesOrderNo")
        sales_order_no.text = order.sales_order_no or None
        for tag, value in (
            ("ExtSourceID", order.external_source_id),
            ("OrderType", order.order_type),
        ):
            if value:
                SubElement(xml, tag).text = value

        if order.customer_id:
            SubElement(xml, "CustomerID").text = order.customer_id
        else:
            SubElement(xml, "ARDivisionNo").text = order.ar_division_no
            SubElement(xml, "CustomerNo").text = order.customer_no

        if order.destination_id:
            SubElement(xml, "DestinationID").text = order.destination_id
        else:
            _add_optional(xml, "ShipToCode", order.ship_to_code)

        for tag, value in (
            ("OrderDate", order.order_date),
            ("ShipExpireDate", order.ship_expire_date),
        ):
            if value:
                SubElement(xml, tag).text = value

        _add_optional(xml, "TaxSchedule", order.tax_schedule)
        _add_optional(xml, "TicketClass", order.ticket_class)
        _add_optional(xml, "CustomerPONo", order.customer_po_no)

        for item in order.items:
            line = SubElement(xml, "line")
            if item.item_code:
                SubElement(line, "ItemCode").text = item.item_code
            else:
                SubElement(line, "ProductID").text = item.product_id
            SubElement(line, "QuantityOrdered").text = format(item.order_quantity, "f")
            _add_optional(line, "WarehouseCode", item.warehouse_code)

        return tostring(root, encoding="utf-8", xml_declaration=False)


def _add_optional(parent: Element, tag: str, value: str | None) -> None:
    """Omit the element when the database value is missing or blank."""
    if value is None:
        return
    text = value.strip()
    if text:
        SubElement(parent, tag).text = text