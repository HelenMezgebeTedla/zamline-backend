from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

EXTREME_VALUE_LIMITS: dict[str, Decimal] = {
    "fuel_price_per_litre": Decimal("60.00"),
    "driver_daily_allowance": Decimal("3000.00"),
    "toll_assumption": Decimal("10000.00"),
    "other_costs": Decimal("20000.00"),
}

MONEY_FIELDS = tuple(EXTREME_VALUE_LIMITS)


class CostSettingsUpdate(BaseModel):
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
    currency: str = "ZMW"
    confirm_extreme_values: bool = False

    def money_updates(self) -> dict[str, Decimal | None]:
        return {
            name: getattr(self, name)
            for name in MONEY_FIELDS
            if name in self.model_fields_set
        }

    def extreme_fields(self) -> list[str]:
        return [
            name
            for name, value in self.money_updates().items()
            if value is not None and value > EXTREME_VALUE_LIMITS[name]
        ]


class CostSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fuel_price_per_litre: Decimal | None
    driver_daily_allowance: Decimal | None
    toll_assumption: Decimal | None
    other_costs: Decimal | None
    currency: str = "ZMW"
    updated_at: datetime | None = None
