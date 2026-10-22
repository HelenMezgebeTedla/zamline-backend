from decimal import Decimal
from uuid import UUID
from datetime import datetime


from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from models.companies import CompanyType, VerificationStatus

EXTREME_VALUE_LIMITS: dict[str, Decimal] = {
    "fuel_price_per_litre": Decimal("60.00"),
    "driver_daily_allowance": Decimal("3000.00"),
    "toll_assumption": Decimal("10000.00"),
    "other_costs": Decimal("20000.00"),
}

MONEY_FIELDS = tuple(EXTREME_VALUE_LIMITS)


class CostSettingsValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fuel_price_per_litre: Decimal | None = Field(
        default=None, gt=0, max_digits=10, decimal_places=2
    )
    driver_daily_allowance: Decimal | None = Field(
        default=None, ge=0, max_digits=10, decimal_places=2
    )
    toll_assumption: Decimal | None = Field(
        default=None, ge=0, max_digits=10, decimal_places=2
    )
    other_costs: Decimal | None = Field(
        default=None, ge=0, max_digits=10, decimal_places=2
    )
    confirm_extreme_values: bool = False

    def money_updates(self) -> dict[str, Decimal | None]:
        return {
            name: getattr(self, name)
            for name in MONEY_FIELDS
            if name in self.model_fields_set
        }

    def money_values(self) -> dict[str, Decimal | None]:
        return {name: getattr(self, name) for name in MONEY_FIELDS}

    def extreme_fields(self) -> list[str]:
        return [
            name
            for name, value in self.money_updates().items()
            if value is not None and value > EXTREME_VALUE_LIMITS[name]
        ]


class CostSettingsUpdate(CostSettingsValues):
    """A partial change of the cost settings."""


class CostSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)
    company_id: UUID
    fuel_price_per_litre: Decimal | None
    driver_daily_allowance: Decimal | None
    toll_assumption: Decimal | None
    other_costs: Decimal | None
    currency: str = "ZMW"
    updated_at: datetime


class CostSettingsCreate(CostSettingsValues):
    model_config = ConfigDict(extra="forbid")

    business_name: str = Field(min_length=2, max_length=100)
    registration_number: str = Field(min_length=2, max_length=20)
    company_email: EmailStr
    phone_number: str = Field(min_length=5, max_length=15)

    fuel_price_per_litre: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    driver_daily_allowance: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=10, decimal_places=2
    )
    toll_assumption: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=10, decimal_places=2
    )
    other_costs: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=10, decimal_places=2
    )

    @field_validator("registration_number")
    @classmethod
    def normalize_registration_number(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("business_name", "phone_number")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class CostSettingsPostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: UUID
    company_type: CompanyType
    business_name: str
    registration_number: str
    company_email: str
    phone_number: str
    verification_status: VerificationStatus
    fuel_price_per_litre: Decimal | None
    driver_daily_allowance: Decimal | None
    toll_assumption: Decimal | None
    other_costs: Decimal | None
    currency: str = "ZMW"
