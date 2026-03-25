from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, UniqueConstraint, func

from src.data.clients.postgres_client import base


class ExchangeRate(base):
    __tablename__ = "exchange_rates"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    rate_date = Column(Date, nullable=False)
    from_currency = Column(String(10), nullable=False)
    to_currency = Column(String(10), nullable=False)
    rate = Column(Numeric(20, 8), nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "rate_date",
            "from_currency",
            "to_currency",
            name="uq_exchange_rate_date_pair",
        ),
    )
