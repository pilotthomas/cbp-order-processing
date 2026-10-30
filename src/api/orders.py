from fastapi import APIRouter, HTTPException, Query

from src.core.config import get_settings
from src.services.cbp_order_list_service import CbpOrderListService
from src.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["Orders"])


def run_order_process(
    status: str = "UNACKNOWLEDGED",
    base_site_id: str = "businessPoint_NA",
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """Import the Chevron list, then send eligible stored orders to Rosetta."""
    settings = get_settings()
    listed = CbpOrderListService().import_orders(
        status=status,
        base_site_id=base_site_id,
        from_date=from_date or settings.cbp_from_date,
        to_date=to_date or settings.cbp_to_date,
    )
    created = OrderService().process_unacknowledged_batch()
    return {"list": listed, "create": created, "summary": summarize_order_process(listed, created)}


def summarize_order_process(listed: dict, created: dict) -> dict:
    """Count every stored order, and keep the Rosetta send counts separate."""
    import_failed = int(listed.get("failed") or 0)
    status_failed = int(listed.get("orderStatusFailed") or 0)
    rosetta_processed = int(created.get("processed") or 0)
    rosetta_succeeded = int(created.get("succeeded") or 0)
    rosetta_failed = int(created.get("failed") or 0)
    return {
        "processed": int(listed.get("stored") or 0) + import_failed,
        "succeeded": rosetta_succeeded,
        "failed": status_failed + rosetta_failed + import_failed,
        "rosettaProcessed": rosetta_processed,
        "rosettaSucceeded": rosetta_succeeded,
        "rosettaFailed": rosetta_failed,
    }


@router.post("/orderProcess")
def order_process(
    status: str = Query(default="UNACKNOWLEDGED"),
    baseSiteid: str = Query(default="businessPoint_NA"),
    fromDate: str | None = Query(default=None),
    toDate: str | None = Query(default=None),
) -> dict:
    """Import the Chevron list, then send eligible stored orders to Rosetta."""
    try:
        return run_order_process(status, baseSiteid, fromDate, toDate)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
