import re
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import ParseError

from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException

from src.schemas.rosetta_response import RosettaResponse

# Rosetta emits control-character references such as &#01; that XML 1.0 forbids.
_INVALID_CHAR_REF = re.compile(
    r"&#(?:0*(?:[0-8]|1[1-2]|1[4-9]|2[0-9]|3[0-1])|x0*(?:[0-8]|[bBcC]|[eEfF]|1[0-9a-fA-F]));"
)
_INVALID_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize(response_xml: bytes | str) -> str:
    text = (
        response_xml.decode("utf-8", errors="replace")
        if isinstance(response_xml, bytes)
        else response_xml
    )
    return _INVALID_CHARS.sub("", _INVALID_CHAR_REF.sub("", text))


class RosettaResponseParser:
    def parse(self, response_xml: bytes | str) -> RosettaResponse:
        try:
            root = fromstring(_sanitize(response_xml))
        except (DefusedXmlException, ParseError, ValueError) as error:
            raise ValueError("Rosetta response is not valid XML") from error

        def text(parent, tag: str) -> str | None:
            element = parent.find(tag)
            if element is None or element.text is None:
                return None
            return element.text.strip() or None

        error_status = text(root, "ErrorStatus")
        if error_status is None:
            raise ValueError("Rosetta response is missing ErrorStatus")
        error_message = text(root, "ErrorMessage")
        if error_status != "0":
            return RosettaResponse(
                success=False,
                error_status=error_status,
                error_message=error_message or "Rosetta returned an error.",
            )

        nested_order = root.find("order")
        order_element = nested_order if nested_order is not None else root

        def decimal_value(parent, tag: str) -> Decimal | None:
            value = text(parent, tag)
            if value is None:
                return None
            try:
                return Decimal(value)
            except InvalidOperation:
                return None

        lines = []
        for line in order_element.findall("line"):
            taxes = [
                {
                    "tax_description": text(tax, "TaxDesc"),
                    "tax_type": text(tax, "TaxType"),
                    "included_in_cost": text(tax, "IncludedInCost"),
                    "tax_rate": decimal_value(tax, "TaxRate"),
                    "fuel_tax_amount": decimal_value(tax, "FuelTaxAmount"),
                }
                for tax in line.findall("fueltax")
            ]
            lines.append(
                {
                    "item_code": text(line, "ItemCode"),
                    "item_description": text(line, "ItemCodeDesc"),
                    "quantity_ordered": decimal_value(line, "QuantityOrdered"),
                    "unit_of_measure": text(line, "UnitOfMeasure"),
                    "unit_price": decimal_value(line, "UnitPrice"),
                    "extension_amount": decimal_value(line, "ExtensionAmt"),
                    "price_contract_details": text(line, "PriceContractDetails"),
                    "fuel_taxes": taxes,
                }
            )
        return RosettaResponse(
            success=True,
            error_status=error_status,
            error_message=error_message,
            order={
                "sales_order_no": text(order_element, "SalesOrderNo")
                or text(order_element, "SALESORDERNO"),
                "order_status": text(order_element, "OrderStatus"),
                "sales_tax_amount": decimal_value(order_element, "SalesTaxAmt"),
                "fuel_tax_amount": decimal_value(order_element, "FuelTaxAmt"),
                "total_order_amount": decimal_value(order_element, "TotalOrderAmt"),
                "lines": lines,
            },
        )