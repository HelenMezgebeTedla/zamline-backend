import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from models.companies import Company
from models.trucks import Truck
from services.errors import ConflictError
from services.routing import RouteSummary

MAX_DRIVING_MINUTES_PER_DAY = 9 * 60
CENTS = Decimal("0.01")


class CostSettingsIncompleteError(ConflictError):
    pass


@dataclass(frozen=True)
class OperatingCostBreakdown:
    fuel_litres: Decimal
    fuel_cost: Decimal
    driver_days: int
    driver_cost: Decimal
    maintenance_cost: Decimal
    toll_cost: Decimal
    other_cost: Decimal

    @property
    def baseline_total(self) -> Decimal:
        return (
            self.fuel_cost
            + self.driver_cost
            + self.maintenance_cost
            + self.toll_cost
            + self.other_cost
        )


def to_money(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def require_cost_settings(company: Company):
    missing = [
        name
        for name in ("fuel_price_per_litre", "driver_daily_allowance")
        if getattr(company, name) is None
    ]
    if missing:
        raise CostSettingsIncompleteError(
            f"Internal cost settings are incomplete: {', '.join(missing)}"
        )


def count_driver_days(duration_minutes: int) -> int:
    return max(1, math.ceil(duration_minutes / MAX_DRIVING_MINUTES_PER_DAY))


def calculate_operating_costs(
    company: Company, truck: Truck, route: RouteSummary
) -> OperatingCostBreakdown:
    require_cost_settings(company)

    distance_km = Decimal(str(route.distance_km))
    litres_per_100km = Decimal(str(truck.fuel_consumption_l_per_100km))
    fuel_litres = distance_km * litres_per_100km / 100
    driver_days = count_driver_days(route.duration_minutes)

    return OperatingCostBreakdown(
        fuel_litres=to_money(fuel_litres),
        fuel_cost=to_money(fuel_litres * Decimal(company.fuel_price_per_litre)),
        driver_days=driver_days,
        driver_cost=to_money(Decimal(company.driver_daily_allowance) * driver_days),
        maintenance_cost=to_money(distance_km * Decimal(truck.maintenance_per_km)),
        toll_cost=to_money(Decimal(company.toll_assumption or 0)),
        other_cost=to_money(Decimal(company.other_costs or 0)),
    )
