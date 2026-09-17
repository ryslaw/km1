from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import Column, Integer, String, DateTime, Numeric, Boolean

from .database import Base


class ChaosState(Base):
    """Single row (id=1) holding the persistent-failure flag — kept in the
    database, so it survives pod restart/reschedule unlike in-process state."""

    __tablename__ = "chaos_state"

    id = Column(Integer, primary_key=True)
    broken = Column(Boolean, nullable=False, default=False)


class Order(Base):
    """ORM model for a confirmed order, persisted after stock is reserved."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    product_id = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    total_price = Column(Numeric(10, 2), nullable=False)
    status = Column(String, default="confirmed")
    created_at = Column(DateTime, default=datetime.utcnow)


class OrderCreate(BaseModel):
    """Request body for POST /orders."""

    user_id: int
    product_id: int
    quantity: int = Field(gt=0)


class OrderOut(BaseModel):
    """Response schema for order endpoints, mirroring the Order ORM model."""

    id: int
    user_id: int
    product_id: int
    quantity: int
    total_price: float
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
