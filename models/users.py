from database import Base
import uuid
import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

TERMS_VERSION = "1.0"


class UserRole(str, enum.Enum):
    SHIPPER = "shipper"
    FLEET_MANAGER = "fleet_manager"


class User(Base):
    __tablename__ = "users"

    user_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.company_id"),
        nullable=False,
        index=True,
    )

    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(
        Enum(
            UserRole,
            values_callable=lambda enum_class: [e.value for e in enum_class],
            name="userrole",
        ),
        nullable=False,
    )
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    terms_accepted_at = Column(
        DateTime(timezone=True), nullable=True, default=func.now()
    )
    terms_version = Column(String(20), nullable=True, default=TERMS_VERSION)

    company = relationship("Company", back_populates="users")
    shipments = relationship("Shipment", back_populates="user")
    shipment_matches = relationship("ShipmentMatch", back_populates="user")
    reservations = relationship("Reservation", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")

    @property
    def terms_accepted(self) -> bool:
        return (
            self.terms_accepted_at is not None and self.terms_version == TERMS_VERSION
        )
