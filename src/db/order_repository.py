from src.core.time import format_rosetta_date, now_chicago
from src.db.connection import get_connection
from src.schemas.order import OrderItem, RosettaOrder


class OrderRepository:
    def get_unacknowledged_order_ids(self, batch_size: int | None = None) -> list[int]:
        limit = "TOP (?)" if batch_size is not None else ""
        statement = f"""
                SELECT {limit} Id
                FROM dbo.CBPOrders
                WHERE CBPOrderStatus = ?
                      AND ISNULL(OrderStatus, '') NOT IN ('SUCCESS', 'FAILED')
                      AND (
                            ErrorDescription IS NULL
                            OR (
                                ErrorDescription NOT LIKE '%already exist%'
                                AND ErrorDescription NOT LIKE '%ItemCode exists more than 1%'
                            )
                          )
                      AND NULLIF(LTRIM(RTRIM(CustomerNo)), '') IS NOT NULL
                ORDER BY Id
                """
        parameters: tuple = (batch_size, "UNACKNOWLEDGED") if batch_size is not None else ("UNACKNOWLEDGED",)
        with get_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, parameters)
            return [row.Id for row in cursor.fetchall()]

    def get_order_for_rosetta(self, order_id: int) -> RosettaOrder | None:
        with get_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT Id, ExtSourceID, SalesOrderNo,
                       ARDivisionNo, CustomerNo, CustomerID, DestinationID,
                       ShipToCode, CBPOrderDate, ShipExpireDate, TaxSchedule,
                       TicketClass, CustomerPONo
                FROM dbo.CBPOrders
                WHERE Id = ?
                """,
                order_id,
            )
            header = cursor.fetchone()
            if header is None:
                return None

            cursor.execute(
                """
                SELECT Id, CBPProductCode, ItemCode, CBPOrderedQty, CBPUnit,
                       WarehouseCode
                FROM dbo.CBPOrderItems
                WHERE CBPOrderId = ?
                ORDER BY Id
                """,
                order_id,
            )
            items = [
                OrderItem(
                    order_item_id=row.Id,
                    product_code=row.CBPProductCode,
                    item_code=row.ItemCode,
                    order_quantity=row.CBPOrderedQty,
                    warehouse_code=row.WarehouseCode,
                    unit=row.CBPUnit,
                )
                for row in cursor.fetchall()
            ]

        return RosettaOrder(
            order_id=header.Id,
            external_source_id=header.ExtSourceID,
            sales_order_no=header.SalesOrderNo,
            ar_division_no=header.ARDivisionNo,
            customer_no=header.CustomerNo,
            customer_id=header.CustomerID,
            destination_id=header.DestinationID,
            ship_to_code=header.ShipToCode,
            order_date=format_rosetta_date(header.CBPOrderDate),
            ship_expire_date=format_rosetta_date(header.ShipExpireDate),
            tax_schedule=header.TaxSchedule,
            ticket_class=header.TicketClass,
            customer_po_no=header.CustomerPONo,
            items=items,
        )

    def update_rosetta_result(
        self,
        order_id: int,
        status: str,
        error_description: str | None = None,
        sales_order_no: str | None = None,
        request_xml: str | None = None,
        response_xml: str | None = None,
    ) -> None:
        # Request and response XML are not stored. Those columns were removed.
        del request_xml, response_xml
        updated_at = now_chicago()
        with get_connection() as connection:
            cursor = connection.cursor()
            set_clauses = [
                "OrderStatus = ?",
                "ErrorDescription = ?",
                "OrderUpdatedAt = ?",
            ]
            params: list[object] = [
                status,
                error_description[:4000] if error_description is not None else None,
                updated_at,
            ]

            if status == "SUCCESS":
                set_clauses.append("CBPCreatedDate = ?")
                params.append(updated_at)

            if sales_order_no is not None:
                set_clauses.append("SalesOrderNo = ?")
                params.append(sales_order_no)

            params.append(order_id)
            cursor.execute(
                f"UPDATE dbo.CBPOrders SET {', '.join(set_clauses)} WHERE Id = ?",
                *params,
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise RuntimeError(
                    f"Could not update CBP result for CBPOrderId {order_id}"
                )

            item_clauses = ["CBPUpdatedDate = ?"]
            item_params: list[object] = [updated_at]
            if status == "SUCCESS":
                item_clauses.append("CBPCreatedDate = ?")
                item_params.append(updated_at)
            if sales_order_no is not None:
                item_clauses.append("SalesOrderNo = ?")
                item_params.append(sales_order_no)
            item_params.append(order_id)
            cursor.execute(
                f"UPDATE dbo.CBPOrderItems SET {', '.join(item_clauses)} WHERE CBPOrderId = ?",
                *item_params,
            )
            connection.commit()

    def update_error_description(
        self,
        order_id: int,
        error_description: str | None = None,
    ) -> None:
        """Store the Rosetta message without changing OrderStatus."""
        with get_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE dbo.CBPOrders
                SET ErrorDescription = ?
                WHERE Id = ?
                """,
                error_description[:4000] if error_description is not None else None,
                order_id,
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise RuntimeError(
                    f"Could not update ErrorDescription for CBPOrderId {order_id}"
                )
            connection.commit()

    def existing_commerce_order_ids(self, commerce_order_ids: list[str]) -> set[str]:
        """Commerce ids already stored. Checked in chunks so a wide date range stays one query pattern."""
        found: set[str] = set()
        if not commerce_order_ids:
            return found
        with get_connection() as connection:
            cursor = connection.cursor()
            for start in range(0, len(commerce_order_ids), 400):
                chunk = commerce_order_ids[start : start + 400]
                placeholders = ",".join("?" for _ in chunk)
                cursor.execute(
                    f"""
                    SELECT CBPCommerceOrderId
                    FROM dbo.CBPOrders
                    WHERE CBPCommerceOrderId IN ({placeholders})
                    """,
                    *chunk,
                )
                found.update(
                    row.CBPCommerceOrderId
                    for row in cursor.fetchall()
                    if row.CBPCommerceOrderId
                )
        return found

    def insert_listed_order(self, header: dict[str, object], items: list[dict[str, object]]) -> int:
        """Insert one CBPOrders row and its CBPOrderItems in a single transaction."""
        now = now_chicago()
        header_columns = [
            "CBPCommerceOrderId",
            "CBPSapOrderId",
            "CBPOrderSource",
            "ExtSourceID",
            "ARDivisionNo",
            "CustomerNo",
            "ShipToCode",
            "ShipExpireDate",
            "TaxSchedule",
            "CustomerPONo",
            "CBPOrderDate",
            "CBPOrderModifiedDate",
            "CBPPurchaseOrderDate",
            "CBPEstimatedDeliveryDate",
            "CBPRequestedDeliveryDate",
            "CBPContactName",
            "CBPContactPhoneNumber",
            "CBPCustomerAccountNumber",
            "CBPContactEmailAddress",
            "CBPDeliveryInstructions",
            "CBPDeliveryMethod",
            "CBPIsRushDelivery",
            "CBPIsRushOrder",
            "CBPCustomerCity",
            "CBPCustomerCountry",
            "CBPCustomerName",
            "CBPCustomerNumber",
            "CBPCustomerPostalCode",
            "CBPCustomerState",
            "CBPCustomerStreetNumber",
            "CBPNewLineItemAllowed",
            "CBPOnContract",
            "CBPPartialUploadAllowed",
            "CBPPodFileRequired",
            "CBPPrefillMustExist",
            "CBPSoldtoExist",
            "CBPFulfilledByCity",
            "CBPFulfilledByCountry",
            "CBPFulfilledByAddress",
            "CBPFulfilledByAddressNumber",
            "CBPFulfilledByState",
            "CBPFulfilledByStreetNumber",
            "CBPOrderStatus",
            "OrderStatus",
            "ErrorDescription",
            "OrderCreatedAt",
            "CBPCreatedDate",
        ]
        header_values = [header.get(column) for column in header_columns]
        header_values[header_columns.index("OrderCreatedAt")] = now
        header_values[header_columns.index("CBPCreatedDate")] = now
        item_columns = [
            "CBPOrderId",
            "CBPCommerceOrderId",
            "CBPSapOrderId",
            "CBPPONumber",
            "ItemCode",
            "WarehouseCode",
            "CBPConsignmentCode",
            "CBPConsignmentSequenceNumber",
            "CBPDefaultScheduledDeliveryDate",
            "CBPDeliveryReceipt",
            "CBPIsAcknowledgementOverdue",
            "CBPIsDeliveryOverdue",
            "CBPConsignmentStatus",
            "CBPScheduledDeliveryDate",
            "CBPEntryNumber",
            "CBPProductCode",
            "CBPBaseProductName",
            "CBPMaxDeliveryQuantity",
            "CBPNewLineItem",
            "CBPOrderedQty",
            "CBPPackageType",
            "CBPPackagingName",
            "CBPShipmentType",
            "CBPUnit",
            "OrderCreatedAt",
            "CBPCreatedDate",
        ]
        with get_connection() as connection:
            cursor = connection.cursor()
            placeholders = ",".join("?" for _ in header_columns)
            cursor.execute(
                f"""
                INSERT INTO dbo.CBPOrders ({", ".join(header_columns)})
                OUTPUT INSERTED.Id
                VALUES ({placeholders})
                """,
                *header_values,
            )
            order_id = int(cursor.fetchone()[0])
            if items:
                item_sql = f"""
                    INSERT INTO dbo.CBPOrderItems ({", ".join(item_columns)})
                    VALUES ({",".join("?" for _ in item_columns)})
                """
                for item in items:
                    values = [item.get(column) for column in item_columns]
                    values[item_columns.index("CBPOrderId")] = order_id
                    values[item_columns.index("OrderCreatedAt")] = now
                    values[item_columns.index("CBPCreatedDate")] = now
                    cursor.execute(item_sql, *values)
            connection.commit()
        return order_id

    def lookup_chevron_buyback(self, customer_account_no: str) -> list[tuple[str, str, str]]:
        """Distinct Sage customer keys for a Chevron customer number."""
        with get_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT DISTINCT ARDivisionNo, CustomerNo, ShipToCode
                FROM dbo.FT_ChevronBuyback
                WHERE LTRIM(RTRIM(CustomerAccountNo)) = ?
                """,
                customer_account_no.strip(),
            )
            return [
                (
                    (row.ARDivisionNo or "").strip(),
                    (row.CustomerNo or "").strip(),
                    (row.ShipToCode or "").strip(),
                )
                for row in cursor.fetchall()
                if (row.CustomerNo or "").strip() and (row.ShipToCode or "").strip()
            ]

    def lookup_ship_to(self, customer_no: str, ship_to_code: str) -> tuple[str | None, str | None]:
        """TaxSchedule and WarehouseCode for the Sage ship-to."""
        with get_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT DISTINCT TaxSchedule, WarehouseCode
                FROM dbo.SO_ShipToAddress
                WHERE LTRIM(RTRIM(CustomerNo)) = ?
                  AND LTRIM(RTRIM(ShipToCode)) = ?
                """,
                customer_no.strip(),
                ship_to_code.strip(),
            )
            rows = cursor.fetchall()
        if len(rows) != 1:
            return None, None
        tax_schedule = (rows[0].TaxSchedule or "").strip() or None
        warehouse_code = (rows[0].WarehouseCode or "").strip() or None
        return tax_schedule, warehouse_code

    def lookup_item_codes(self, vendor_alias: str) -> list[str]:
        """Item codes whose vendor alias is the product code, or that code plus a suffix."""
        alias = vendor_alias.strip()
        with get_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT DISTINCT ItemCode
                FROM dbo.IM_ItemVendor
                WHERE VendorAliasItemNo = ?
                   OR VendorAliasItemNo LIKE ?
                   OR VendorAliasItemNo LIKE ?
                """,
                alias,
                alias + "/%",
                alias + " %",
            )
            return sorted(
                {
                    (row.ItemCode or "").strip()
                    for row in cursor.fetchall()
                    if (row.ItemCode or "").strip()
                }
            )
