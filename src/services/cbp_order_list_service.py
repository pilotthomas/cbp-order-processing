import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import requests

from src.core.config import Settings, get_settings
from src.core.logger import logger
from src.db.order_repository import OrderRepository

_lock = threading.Lock()
_cached_token: str | None = None
_cached_expires_at: float = 0.0


class CbpOrderListService:
    def __init__(
        self,
        settings: Settings | None = None,
        repository: OrderRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or OrderRepository()

    def import_orders(
        self,
        status: str,
        base_site_id: str,
        from_date: str,
        to_date: str,
    ) -> dict[str, Any]:
        """List orders for the date range, then store details for ids not already in SQL."""
        logger.info(
            "list_orders started status=%s baseSiteid=%s fromDate=%s toDate=%s",
            status,
            base_site_id,
            from_date,
            to_date,
        )
        listed = self.list_orders(status, base_site_id, from_date, to_date)
        rows = listed.get("orderList") if isinstance(listed, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("CBP order list response did not include orderList")

        commerce_ids: list[str] = []
        seen: set[str] = set()
        for row in rows:
            commerce_id = str((row or {}).get("commerceOrderId") or "").strip()
            if commerce_id and commerce_id not in seen:
                seen.add(commerce_id)
                commerce_ids.append(commerce_id)

        existing = self.repository.existing_commerce_order_ids(commerce_ids)
        pending = [commerce_id for commerce_id in commerce_ids if commerce_id not in existing]
        logger.info(
            "list_orders received count=%s already_stored=%s pending=%s",
            len(commerce_ids),
            len(commerce_ids) - len(pending),
            len(pending),
        )
        stored = 0
        order_status_failed = 0
        failures: list[dict[str, str]] = []
        if pending:
            workers = min(self.settings.cbp_detail_concurrency, len(pending))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(self._import_one, commerce_id, base_site_id): commerce_id
                    for commerce_id in pending
                }
                for future in as_completed(futures):
                    commerce_id = futures[future]
                    try:
                        order_status = future.result()
                        stored += 1
                        if order_status == "FAILED":
                            order_status_failed += 1
                    except Exception as error:
                        logger.error(
                            "CBP order import failed commerceOrderId=%s error=%s",
                            commerce_id,
                            error,
                        )
                        failures.append(
                            {"commerceOrderId": commerce_id, "error": str(error)}
                        )
        logger.info(
            "CBP order import listed=%s already_stored=%s stored=%s failed=%s",
            len(commerce_ids),
            len(commerce_ids) - len(pending),
            stored,
            len(failures),
        )
        return {
            "listed": len(commerce_ids),
            "alreadyStored": len(commerce_ids) - len(pending),
            "stored": stored,
            "orderStatusFailed": order_status_failed,
            "failed": len(failures),
            "failures": failures[:20],
            "orderList": rows,
        }

    def get_order(self, base_site_id: str, commerce_order_id: str) -> dict[str, Any]:
        self._require_config()
        if not self.settings.cbp_order_detail_url:
            raise RuntimeError("CBP order list is not configured. Set CBP_ORDER_DETAIL_URL.")
        payload = self._get_json(
            self.settings.cbp_order_detail_url,
            {
                "searchCriteria": "commerceOrderId",
                "baseSiteid": base_site_id,
                "searchValueId": commerce_order_id,
            },
        )
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"CBP order detail for {commerce_order_id} was not a JSON object"
            )
        logger.info(
            "Get Order completed commerceOrderId=%s status=%s lines=%s",
            commerce_order_id,
            payload.get("status"),
            sum(len(row.get("entries") or []) for row in payload.get("consignments") or []),
        )
        return payload

    def _import_one(self, commerce_order_id: str, base_site_id: str) -> str:
        logger.info("Get Order started commerceOrderId=%s", commerce_order_id)
        detail = self.get_order(base_site_id, commerce_order_id)
        header, items = _map_order(detail)
        _apply_sage_lookups(self.repository, header, items)
        order_id = self.repository.insert_listed_order(header, items)
        order_status = str(header.get("OrderStatus") or "")
        logger.info(
            "Stored CBP order CBPOrderId=%s commerceOrderId=%s lines=%s OrderStatus=%s CustomerNo=%s",
            order_id,
            commerce_order_id,
            len(items),
            order_status or "PENDING",
            header.get("CustomerNo"),
        )
        return order_status

    def list_orders(
        self,
        status: str,
        base_site_id: str,
        from_date: str,
        to_date: str,
    ) -> Any:
        self._require_config()
        payload = self._get_json(
            self.settings.cbp_order_list_url,
            {
                "status": status,
                "baseSiteid": base_site_id,
                "fromDate": from_date,
                "toDate": to_date,
            },
        )
        if isinstance(payload, dict):
            return payload
        raise RuntimeError("CBP order list response was not a JSON object")

    def _require_config(self) -> None:
        missing = [
            name
            for name, value in (
                ("CBP_TOKEN_URL", self.settings.cbp_token_url),
                ("CBP_CLIENT_ID", self.settings.cbp_client_id),
                ("CBP_CLIENT_SECRET", self.settings.cbp_client_secret),
                ("CBP_RESOURCE", self.settings.cbp_resource),
                ("CBP_ORDER_LIST_URL", self.settings.cbp_order_list_url),
                ("CBP_SUBSCRIPTION_KEY", self.settings.cbp_subscription_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"CBP order list is not configured. Set {', '.join(missing)}.")

    def _get_json(self, url: str, params: dict[str, str]) -> Any:
        response = self._get(url, params)
        if response.status_code >= 400:
            logger.error(
                "CBP request failed url=%s status=%s body=%s",
                url,
                response.status_code,
                response.text[:500],
            )
            raise RuntimeError(
                f"CBP request failed with status {response.status_code}: {response.text[:500]}"
            )
        return response.json()

    def _get(self, url: str, params: dict[str, str]) -> requests.Response:
        response = self._authorized_get(url, params)
        if response.status_code != 401:
            return response
        self._clear_token()
        return self._authorized_get(url, params)

    def _authorized_get(self, url: str, params: dict[str, str]) -> requests.Response:
        return requests.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Ocp-Apim-Subscription-Key": self.settings.cbp_subscription_key,
                "Accept": "application/json",
            },
            timeout=60,
        )

    def _clear_token(self) -> None:
        global _cached_token, _cached_expires_at
        with _lock:
            _cached_token = None
            _cached_expires_at = 0.0

    def _access_token(self) -> str:
        global _cached_token, _cached_expires_at
        now = time.time()
        skew = self.settings.cbp_token_refresh_skew_seconds
        with _lock:
            if _cached_token and now < _cached_expires_at - skew:
                return _cached_token
            token, expires_at = self._request_token()
            _cached_token = token
            _cached_expires_at = expires_at
            logger.info(
                "CBP token acquired expires_in_seconds=%s",
                max(int(expires_at - now), 0),
            )
            return token

    def _request_token(self) -> tuple[str, float]:
        response = requests.post(
            self.settings.cbp_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.settings.cbp_client_id,
                "client_secret": self.settings.cbp_client_secret,
                "resource": self.settings.cbp_resource,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if response.status_code >= 400:
            logger.error(
                "CBP token request failed status=%s body=%s",
                response.status_code,
                response.text[:500],
            )
            raise RuntimeError(
                f"CBP token request failed with status {response.status_code}"
            )
        payload = response.json()
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("CBP token response did not include an access_token")
        expires_at = _expiry(payload)
        return token, expires_at


def _map_order(detail: dict[str, Any]) -> tuple[dict[str, object], list[dict[str, object]]]:
    location = detail.get("customerLocation") or {}
    restrictions = location.get("restrictionData") or {}
    fulfilled = detail.get("fulfilledBy") or {}
    customer_number = _text(location.get("customerNumber"), 50)
    commerce_id = _text(detail.get("commerceOrderId"), 50)
    sap_order_id = _text(detail.get("sapOrderId"), 50)
    po_number = _text(detail.get("poNumber"), 100)
    header: dict[str, object] = {
        "CBPCommerceOrderId": commerce_id,
        "CBPSapOrderId": sap_order_id,
        "CBPOrderSource": _text(detail.get("orderSource"), 50),
        "CustomerPONo": po_number,
        "CBPOrderDate": _date(detail.get("orderDate")),
        "CBPOrderModifiedDate": _date(detail.get("orderModifiedDate")),
        "CBPPurchaseOrderDate": _date(detail.get("purchaseOrderDate")),
        "CBPEstimatedDeliveryDate": _date(detail.get("estimatedDeliveryDate")),
        "CBPRequestedDeliveryDate": _date(detail.get("requestedDeliveryDate")),
        "CBPContactName": _text(detail.get("contactName"), 100),
        "CBPContactPhoneNumber": _text(detail.get("contactPhoneNumber"), 50),
        "CBPCustomerAccountNumber": _text(detail.get("customerAccountNumber"), 50),
        "CBPContactEmailAddress": _text(detail.get("contactEmailAddress"), 100),
        "CBPDeliveryInstructions": _text(detail.get("deliveryInstructions"), None),
        "CBPDeliveryMethod": _text(detail.get("deliveryMethod"), 10),
        "CBPIsRushDelivery": _bit(detail.get("isRushDelivery")),
        "CBPIsRushOrder": _text(detail.get("isRushOrder"), 50),
        "CBPCustomerCity": _text(location.get("city"), 100),
        "CBPCustomerCountry": _text(location.get("country"), 100),
        "CBPCustomerName": _text(location.get("customerName"), 200),
        "CBPCustomerNumber": customer_number,
        "CBPCustomerPostalCode": _text(location.get("postalCode"), 20),
        "CBPCustomerState": _text(location.get("state"), 100),
        "CBPCustomerStreetNumber": _text(location.get("streetNumber"), 200),
        "CBPNewLineItemAllowed": _bit(restrictions.get("newLineItemAllowed")),
        "CBPOnContract": _bit(restrictions.get("onContract")),
        "CBPPartialUploadAllowed": _bit(restrictions.get("partialUploadAllowed")),
        "CBPPodFileRequired": _bit(restrictions.get("podFileRequired")),
        "CBPPrefillMustExist": _bit(restrictions.get("prefillMustExist")),
        "CBPSoldtoExist": _bit(restrictions.get("soldtoExist")),
        "CBPFulfilledByCity": _text(fulfilled.get("city"), 100),
        "CBPFulfilledByCountry": _text(fulfilled.get("country"), 100),
        "CBPFulfilledByAddress": _text(fulfilled.get("fulfilledByAddress"), None),
        "CBPFulfilledByAddressNumber": _text(fulfilled.get("fulfilledByAddressNumber"), 50),
        "CBPFulfilledByState": _text(fulfilled.get("state"), 100),
        "CBPFulfilledByStreetNumber": _text(fulfilled.get("streetNumber"), 200),
        "CBPOrderStatus": _text(detail.get("status"), 50),
        "ShipExpireDate": _date(detail.get("requestedDeliveryDate")),
    }
    items: list[dict[str, object]] = []
    for consignment in detail.get("consignments") or []:
        for entry in consignment.get("entries") or []:
            items.append(
                {
                    "CBPCommerceOrderId": commerce_id,
                    "CBPSapOrderId": sap_order_id,
                    "CBPPONumber": po_number,
                    "CBPConsignmentCode": _text(consignment.get("code"), 50),
                    "CBPConsignmentSequenceNumber": _text(
                        consignment.get("consignmentSequenceNumber"), 10
                    ),
                    "CBPDefaultScheduledDeliveryDate": _date(
                        consignment.get("defaultScheduledDeliveryDate")
                    ),
                    "CBPDeliveryReceipt": _text(consignment.get("deliveryReceipt"), 50),
                    "CBPIsAcknowledgementOverdue": _bit(
                        consignment.get("isAcknowledgementOverdue")
                    ),
                    "CBPIsDeliveryOverdue": _bit(consignment.get("isDeliveryOverdue")),
                    "CBPConsignmentStatus": _text(consignment.get("status"), 50),
                    "CBPScheduledDeliveryDate": _date(consignment.get("scheduledDeliveryDate")),
                    "CBPEntryNumber": _int(entry.get("entryNumber")),
                    "CBPProductCode": _text(entry.get("code"), 50),
                    "CBPBaseProductName": _text(entry.get("baseProductName"), 200),
                    "CBPMaxDeliveryQuantity": _decimal(entry.get("maxDeliveryQuantity")),
                    "CBPNewLineItem": _bit(entry.get("newLineItem")),
                    "CBPOrderedQty": _decimal(entry.get("orderedQty")),
                    "CBPPackageType": _text(entry.get("packageType"), 50),
                    "CBPPackagingName": _text(entry.get("packagingName"), 200),
                    "CBPShipmentType": _text(entry.get("shipmentType"), 50),
                    "CBPUnit": _text(entry.get("unit"), 20),
                }
            )
    return header, items


def _apply_sage_lookups(repository: OrderRepository, header: dict[str, object], items: list[dict[str, object]]) -> None:
    """Fill Sage customer, ship-to, tax, warehouse, and item code from MAS tables."""
    header["CustomerNo"] = None
    customer_number = header.get("CBPCustomerNumber")
    if not isinstance(customer_number, str) or not customer_number.strip():
        return
    matches = repository.lookup_chevron_buyback(customer_number)
    if len(matches) != 1:
        header["OrderStatus"] = "FAILED"
        header["ErrorDescription"] = (
            "FT_ChevronBuyback matched more than one ship-to."
            if matches
            else "FT_ChevronBuyback has no row for customerNumber."
        )
        logger.error(
            "Chevron buyback lookup commerceOrderId=%s customerNumber=%s matches=%s",
            header.get("CBPCommerceOrderId"),
            customer_number,
            len(matches),
        )
        return
    ar_division_no, customer_no, ship_to_code = matches[0]
    header["ARDivisionNo"] = _text(ar_division_no, 20)
    header["CustomerNo"] = _text(customer_no, 50)
    header["ShipToCode"] = _text(ship_to_code, 4)
    tax_schedule, warehouse_code = repository.lookup_ship_to(customer_no, ship_to_code)
    header["TaxSchedule"] = _text(tax_schedule, 50)
    warehouse_code = _text(warehouse_code, 3)
    duplicate_item = False
    for item in items:
        item["WarehouseCode"] = warehouse_code
        product_code = item.get("CBPProductCode")
        alias = _vendor_alias(product_code if isinstance(product_code, str) else None)
        item_codes = repository.lookup_item_codes(alias) if alias else []
        if len(item_codes) == 1:
            item["ItemCode"] = _text(item_codes[0], 100)
        elif len(item_codes) > 1:
            duplicate_item = True
            logger.error(
                "ItemCode exists more than 1 commerceOrderId=%s productCode=%s alias=%s count=%s",
                header.get("CBPCommerceOrderId"),
                product_code,
                alias,
                len(item_codes),
            )
    if duplicate_item:
        header["OrderStatus"] = "FAILED"
        header["ErrorDescription"] = "ItemCode exists more than 1."


def _vendor_alias(product_code: str | None) -> str | None:
    """227077982 becomes 227077/982, the vendor alias prefix."""
    if not product_code:
        return None
    code = product_code.strip()
    if len(code) <= 6:
        return None
    return f"{code[:6]}/{code[6:]}"


def _text(value: Any, limit: int | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if limit is not None and len(text) > limit:
        return text[:limit]
    return text


def _date(value: Any) -> date | None:
    text = _text(value, None)
    if text is None:
        return None
    for pattern in ("%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    logger.warning("CBP date skipped value=%s", text)
    return None


def _bit(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _int(value: Any) -> int | None:
    text = _text(value, None)
    if text is None:
        return None
    return int(text)


def _decimal(value: Any) -> Decimal | None:
    text = _text(value, None)
    if text is None:
        return None
    return Decimal(text)


def _expiry(payload: dict[str, Any]) -> float:
    expires_on = payload.get("expires_on")
    if expires_on not in (None, ""):
        return float(expires_on)
    expires_in = payload.get("expires_in") or 3600
    return time.time() + float(expires_in)
