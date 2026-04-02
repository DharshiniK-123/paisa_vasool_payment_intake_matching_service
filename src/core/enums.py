from enum import Enum

class DocumentType(str, Enum):
    INVOICE = "INVOICE"
    PAYMENT = "PAYMENT"

class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    EXTRACTED = "EXTRACTED"
    PARSED = "PARSED"
    FAILED = "FAILED"

class MatchStatus(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    OVERPAYMENT = "OVERPAYMENT"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"
    SUGGESTED = "SUGGESTED"
    MANUALLY_MATCHED = "MANUALLY_MATCHED"

class InvoicePaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERPAID = "OVERPAID"


class AgingSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    SCHEDULER = "SCHEDULER"


class ReminderChannel(str, Enum):
    EMAIL = "EMAIL"


class ReminderStatus(str, Enum):
    SENT = "SENT"
    FAILED = "FAILED"
