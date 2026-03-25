import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.core.services.aging_service import get_overdue_invoices_with_bucket
from src.core.services.reminder_service import process_reminder
from src.data.clients.postgres_client import AsyncSessionLocal

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/payment/aging/run")
async def aging_run_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        async with AsyncSessionLocal() as db:
            await websocket.send_json(
                {
                    "type": "status",
                    "message": "Scanning overdue invoices...",
                }
            )

            overdue_items = await get_overdue_invoices_with_bucket(db)

            if not overdue_items:
                await websocket.send_json(
                    {
                        "type": "done",
                        "message": "No overdue invoices found.",
                        "sent": 0,
                        "skipped": 0,
                        "failed": 0,
                    }
                )
                return

            await websocket.send_json(
                {
                    "type": "status",
                    "message": f"Found {len(overdue_items)} overdue invoice(s). Processing...",
                    "total": len(overdue_items),
                }
            )

            generated = skipped = failed = 0

            for index, item in enumerate(overdue_items, start=1):
                invoice = item["invoice"]
                try:
                    reminder = await process_reminder(
                        invoice,
                        item["days_overdue"],
                        item["config"],
                        db,
                    )

                    if reminder is None:
                        skipped += 1
                        await websocket.send_json(
                            {
                                "type": "skipped",
                                "index": index,
                                "total": len(overdue_items),
                                "invoice": invoice.invoice_number,
                                "message": f"""{invoice.invoice_number} — 
                            skipped (reminder sent recently)""",
                            }
                        )
                    else:
                        generated += 1
                        await websocket.send_json(
                            {
                                "type": "sent",
                                "index": index,
                                "total": len(overdue_items),
                                "invoice": invoice.invoice_number,
                                "severity": item["config"].severity,
                                "message": f"""{invoice.invoice_number} → 
                            {item['config'].severity} — reminder sent ✓""",
                            }
                        )

                except Exception as e:
                    failed += 1
                    logger.error(
                        "ws_reminder_failed",
                        extra={"invoice_id": invoice.id, "error": str(e)},
                    )
                    await websocket.send_json(
                        {
                            "type": "error",
                            "index": index,
                            "total": len(overdue_items),
                            "invoice": invoice.invoice_number,
                            "message": f"{invoice.invoice_number} — failed: {str(e)}",
                        }
                    )

            await db.commit()
            await websocket.send_json(
                {
                    "type": "done",
                    "message": f"""Aging job complete — sent: {generated},
                 skipped: {skipped}, failed: {failed}""",
                    "sent": generated,
                    "skipped": skipped,
                    "failed": failed,
                }
            )

    except WebSocketDisconnect:
        logger.info("aging_ws_client_disconnected")

    except Exception as e:
        logger.error("aging_ws_fatal_error", extra={"error": str(e)})
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Aging job failed unexpectedly. Please try again.",
                }
            )
        except Exception:
            raise
