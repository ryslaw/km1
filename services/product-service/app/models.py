from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Numeric, Boolean

from .database import Base


class Product(Base):
    """ORM model for a sellable product, including current stock level."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    stock = Column(Integer, nullable=False, default=0)


class ChaosState(Base):
    """Single row (id=1) holding the persistent-failure flag — kept in the
    database, so it survives pod restart/reschedule unlike in-process state."""

    __tablename__ = "chaos_state"

    id = Column(Integer, primary_key=True)
    broken = Column(Boolean, nullable=False, default=False)


class ProductCreate(BaseModel):
    """Request body for POST /products."""

    name: str
    price: float = Field(gt=0)
    stock: int = Field(ge=0)


class ProductOut(BaseModel):
    """Response schema for product endpoints, mirroring the Product ORM model."""

    id: int
    name: str
    price: float
    stock: int

    class Config:
        from_attributes = True


class StockReservation(BaseModel):
    """Request body for POST /products/{product_id}/reserve."""

    quantity: int = Field(gt=0)
