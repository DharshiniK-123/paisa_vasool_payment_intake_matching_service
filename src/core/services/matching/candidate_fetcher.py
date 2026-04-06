import logging
from dataclasses import dataclass, field

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.matching_payment_invoice import MatchingPaymentInvoice
from src.utils.normalize import _normalize

logger = logging.getLogger(__name__)


@dataclass
class CandidateSet:
    """Categorized invoice buckets for one payment."""
    same_currency:   list[InvoiceData] = field(default_factory=list)
    fx_mismatch:     list[InvoiceData] = field(default_factory=list)
    already_paid:    list[InvoiceData] = field(default_factory=list)
    deleted:         list[InvoiceData] = field(default_factory=list)
    deep_candidates: list[InvoiceData] = field(default_factory=list) 

    def has_open(self) -> bool:
        return bool(self.same_currency or self.fx_mismatch or self.deep_candidates)

    def best_failure_reason(self, payment, invoice_nos: list[str]) -> str:
        """
        Returns the most specific failure reason when no open candidates exist.
        """
        for inv in self.already_paid:
            inv_num = _normalize(str(inv.invoice_number or ""))
            if any(n == inv_num or inv_num in n or n in inv_num for n in invoice_nos):
                return (
                    f"Invoice '{inv.invoice_number}' has already been fully paid by a "
                    "previous payment. This payment cannot be applied to it again. "
                    "Please verify whether a duplicate payment was made."
                )

        for inv in self.deleted:
            inv_num = _normalize(str(inv.invoice_number or ""))
            if any(n == inv_num or inv_num in n or n in inv_num for n in invoice_nos):
                return (
                    f"Invoice '{inv.invoice_number}' exists but has been deleted/archived "
                    "and cannot receive payments. Please contact your finance team to "
                    "restore the invoice or redirect this payment."
                )

        if not invoice_nos:
            return (
                "No invoice number was provided with this payment and no open invoices "
                "could be matched by amount or customer. Manual assignment is required."
            )

        return (
            "No open invoices were found for customer. "
            "Either all invoices are already fully paid, or the customer detail does not "
            "match any invoice on record."
        )


class CandidateFetcher:
    """
    Fetches and categorizes invoices for a given payment in a single pass.

    Two paths:
      - invoice_no present  → filter open invoices by number, split by currency (existing)
      - invoice_no absent   → populate deep_candidates with all open same-currency invoices
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def fetch(self, payment, invoice_nos: list[str]) -> CandidateSet:
        fully_paid_subq = (
            select(MatchingPaymentInvoice.invoice_id)
            .where(MatchingPaymentInvoice.match_status == "FULL")
        )

        # Fetch open (not fully paid, not deleted) invoices for this customer
        open_result = await self.db.execute(
            select(InvoiceData).where(
                and_(
                    InvoiceData.customer_id == payment.customer_id,
                    InvoiceData.id.notin_(fully_paid_subq),
                    InvoiceData.is_deleted.is_(False),
                )
            )
        )
        open_invoices: list[InvoiceData] = list(open_result.scalars().all())

        # Fetch already fully-paid (for better error messages)
        paid_result = await self.db.execute(
            select(InvoiceData).where(
                and_(
                    InvoiceData.customer_id == payment.customer_id,
                    InvoiceData.id.in_(fully_paid_subq),
                    InvoiceData.is_deleted.is_(False),
                )
            )
        )
        already_paid: list[InvoiceData] = list(paid_result.scalars().all())

        # Fetch soft-deleted (for better error messages)
        deleted_result = await self.db.execute(
            select(InvoiceData).where(
                and_(
                    InvoiceData.customer_id == payment.customer_id,
                    InvoiceData.is_deleted.is_(True),
                )
            )
        )
        deleted: list[InvoiceData] = list(deleted_result.scalars().all())

        same_currency:   list[InvoiceData] = []
        fx_mismatch:     list[InvoiceData] = []
        deep_candidates: list[InvoiceData] = []

        if invoice_nos:
            for inv in open_invoices:
                inv_num    = _normalize(str(inv.invoice_number or ""))
                number_hit = any(
                    n == inv_num or inv_num in n or n in inv_num
                    for n in invoice_nos
                )
                if not number_hit:
                    continue
                if payment.currency == inv.currency:
                    same_currency.append(inv)
                else:
                    fx_mismatch.append(inv)
        else:
            for inv in open_invoices:
                if payment.currency == inv.currency:
                    deep_candidates.append(inv)
                else:
                    fx_mismatch.append(inv)  

        logger.debug(
            "candidate_fetch",
            extra={
                "payment_id":      payment.id,
                "same_currency":   len(same_currency),
                "fx_mismatch":     len(fx_mismatch),
                "deep_candidates": len(deep_candidates),
                "already_paid":    len(already_paid),
                "deleted":         len(deleted),
            },
        )

        return CandidateSet(
            same_currency=same_currency,
            fx_mismatch=fx_mismatch,
            already_paid=already_paid,
            deleted=deleted,
            deep_candidates=deep_candidates,
        )
