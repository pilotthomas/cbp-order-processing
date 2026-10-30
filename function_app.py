import azure.functions as func
from fastapi import FastAPI

from src.api.orders import router as orders_router
from src.api.orders import run_order_process
from src.core.config import get_settings
from src.core.logger import log_exception, logger

fastapi_app = FastAPI(
    title="Sage Automation API",
    description="CBP order processing and Sage integration APIs",
    version="1.0.0",
)

fastapi_app.include_router(orders_router)

@fastapi_app.get("/health", tags=["Health"])
def health():
    return {"message": "Sage Automation API is running!"}

app = func.AsgiFunctionApp(
    app=fastapi_app,
    http_auth_level=func.AuthLevel.ANONYMOUS,
)


@app.timer_trigger(
    schedule="%ORDER_PROCESS_CRON%",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def order_process_timer(timer: func.TimerRequest) -> None:
    """Import Chevron orders, then send eligible rows to Rosetta."""
    if timer.past_due:
        logger.warning("order_process_timer is past due")
    settings = get_settings()
    logger.info(
        "order_process_timer started status=%s baseSiteid=%s fromDate=%s toDate=%s",
        settings.cbp_list_status,
        settings.cbp_base_site_id,
        settings.cbp_from_date,
        settings.cbp_to_date,
    )
    try:
        result = run_order_process(
            status=settings.cbp_list_status,
            base_site_id=settings.cbp_base_site_id,
            from_date=settings.cbp_from_date,
            to_date=settings.cbp_to_date,
        )
    except Exception as exc:
        log_exception("order_process_timer failed", exc)
        raise
    summary = result["summary"]
    logger.info(
        "order_process_timer completed processed=%s succeeded=%s failed=%s",
        summary["processed"],
        summary["succeeded"],
        summary["failed"],
    )
    logger.info(
        "order_process_timer rosetta processed=%s succeeded=%s failed=%s",
        summary["rosettaProcessed"],
        summary["rosettaSucceeded"],
        summary["rosettaFailed"],
    )
