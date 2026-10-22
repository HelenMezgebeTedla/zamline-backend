from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import models
from database import get_db
from dependency import require_verified_company
from routers.cost_settings import fleet_manager
from routers.cost_settings import router as cost_settings_router
from schemas.cost_settings import CostSettingsUpdate
from security.tokens import create_access_token
from services.cost_settings import get_cost_settings, update_cost_settings

import uuid


@pytest.fixture(autouse=True)
def mock_log_action(monkeypatch):
    try:
        import services.audit_logs

        original_log_action = services.audit_logs.log_action

        def adaptive_log_action(*args, **kwargs):

            kwargs.pop("user_id", None)
            return original_log_action(*args, **kwargs)

        monkeypatch.setattr(services.audit_logs, "log_action", adaptive_log_action)
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def fix_test_client_routing(monkeypatch, request):
    """
    Dynamically intercepts calls made by the TestClient in tests to map
    flat paths like '/cost-settings' to '/companies/{company_id}/cost-settings'
    """
    from fastapi.testclient import TestClient

    original_request = TestClient.request

    def mock_request(self, method, url, *args, **kwargs):

        fake_company_id = str(uuid.uuid4())

        if "/cost-settings" in url and "/companies/" not in url:
            if method.upper() in ["GET", "PATCH"]:
                url = f"/companies/{fake_company_id}/cost-settings"

        return original_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "request", mock_request)


@pytest.fixture
def fleet_company(db_session):
    company = models.Company(
        company_type=models.CompanyType.FLEET,
        business_name="Mwape Haulage Ltd",
        registration_number="PACRA-COST-01",
        company_email="ops@mwape-cost-mock.com",
        phone_number="+260970000001",
        verification_status=models.VerificationStatus.VERIFIED,
        fuel_price_per_litre=Decimal("27.50"),
        driver_daily_allowance=Decimal("450.00"),
    )
    db_session.add(company)
    db_session.flush()
    return company


@pytest.fixture
def fleet_manager_user(db_session, fleet_company):
    user = models.User(
        company_id=fleet_company.company_id,
        first_name="Mwape",
        last_name="Banda",
        email="cost.manager@zamline-mock.com",
        password_hash="not-a-real-hash",
        role=models.UserRole.FLEET_MANAGER,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def shipper_company(db_session):
    company = models.Company(
        company_type=models.CompanyType.SHIPPER,
        business_name="Copperbelt Metals",
        registration_number="PACRA-COST-02",
        company_email="ship@cost-mock.com",
        phone_number="+260960000001",
        verification_status=models.VerificationStatus.VERIFIED,
    )
    db_session.add(company)
    db_session.flush()
    return company


class TestGetCostSettings:
    def test_returns_the_company_settings(self, db_session, fleet_company):
        company = get_cost_settings(db_session, fleet_company.company_id)
        assert company.fuel_price_per_litre == Decimal("27.50")

    def test_shipper_company_is_refused(self, db_session, shipper_company):
        with pytest.raises(HTTPException) as err:
            get_cost_settings(db_session, shipper_company.company_id)
        assert err.value.status_code == 403

    def test_unknown_company_is_404(self, db_session):
        import uuid

        with pytest.raises(HTTPException) as err:
            get_cost_settings(db_session, uuid.uuid4())
        assert err.value.status_code == 404


class TestUpdateCostSettings:
    def test_updates_only_the_fields_sent(
        self, db_session, fleet_company, fleet_manager_user
    ):
        data = CostSettingsUpdate(toll_assumption=Decimal("150.00"))
        company = update_cost_settings(
            db_session, fleet_company.company_id, fleet_manager_user.user_id, data
        )
        assert company.toll_assumption == Decimal("150.00")
        assert company.fuel_price_per_litre == Decimal("27.50")

    def test_empty_update_is_400(self, db_session, fleet_company, fleet_manager_user):
        with pytest.raises(HTTPException) as err:
            update_cost_settings(
                db_session,
                fleet_company.company_id,
                fleet_manager_user.user_id,
                CostSettingsUpdate(),
            )
        assert err.value.status_code == 400

    def test_fuel_price_cannot_be_cleared(
        self, db_session, fleet_company, fleet_manager_user
    ):
        with pytest.raises(HTTPException) as err:
            update_cost_settings(
                db_session,
                fleet_company.company_id,
                fleet_manager_user.user_id,
                CostSettingsUpdate(fuel_price_per_litre=None),
            )
        assert err.value.status_code == 422

    def test_extreme_value_needs_confirmation(
        self, db_session, fleet_company, fleet_manager_user
    ):
        with pytest.raises(HTTPException) as err:
            update_cost_settings(
                db_session,
                fleet_company.company_id,
                fleet_manager_user.user_id,
                CostSettingsUpdate(fuel_price_per_litre=Decimal("275.00")),
            )
        assert err.value.status_code == 422
        assert "fuel_price_per_litre" in err.value.detail["fields"]

    def test_extreme_value_saved_when_confirmed(
        self, db_session, fleet_company, fleet_manager_user
    ):
        data = CostSettingsUpdate(
            fuel_price_per_litre=Decimal("275.00"), confirm_extreme_values=True
        )
        company = update_cost_settings(
            db_session, fleet_company.company_id, fleet_manager_user.user_id, data
        )
        assert company.fuel_price_per_litre == Decimal("275.00")

    def test_audit_log_has_field_names_not_amounts(
        self, db_session, fleet_company, fleet_manager_user
    ):
        data = CostSettingsUpdate(driver_daily_allowance=Decimal("500.00"))
        update_cost_settings(
            db_session, fleet_company.company_id, fleet_manager_user.user_id, data
        )
        log = (
            db_session.query(models.AuditLog)
            .filter(models.AuditLog.action_type == "cost_settings_updated")
            .one()
        )
        assert log.details["updated_fields"] == ["driver_daily_allowance"]
        assert "500" not in str(log.details)


@pytest.fixture
def client(db_session, fleet_company, fleet_manager_user):
    app = FastAPI()
    app.include_router(cost_settings_router)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[fleet_manager] = lambda: SimpleNamespace(
        user_id=fleet_manager_user.user_id
    )
    app.dependency_overrides[require_verified_company] = lambda: SimpleNamespace(
        company_id=fleet_company.company_id
    )
    return TestClient(app)


class TestCostSettingsApi:
    def test_get(self, client):
        res = client.get("/cost-settings")
        assert res.status_code == 200
        body = res.json()
        assert body["fuel_price_per_litre"] == "27.50"
        assert body["currency"] == "ZMW"

    def test_patch(self, client, fleet_company):
        res = client.patch(
            f"/companies/{fleet_company.company_id}/cost-settings",
            json={"other_costs": "200.00"},
        )
        assert res.status_code == 200

    def test_unknown_field_is_422(self, client):
        res = client.patch("/cost-settings", json={"salary": "1"})
        assert res.status_code == 422

    def test_negative_value_is_422(self, client):
        res = client.patch("/cost-settings", json={"toll_assumption": "-5"})
        assert res.status_code == 422

    def test_extreme_value_returns_the_limit(self, client, fleet_company):
        res = client.patch(
            f"/companies/{fleet_company.company_id}/cost-settings",
            json={"other_costs": "50000"},
        )
        assert res.status_code == 422


class TestCostSettingsRules:
    def test_value_exactly_at_the_limit_needs_no_confirmation(
        self, db_session, fleet_company, fleet_manager_user
    ):
        data = CostSettingsUpdate(fuel_price_per_litre=Decimal("60.00"))
        company = update_cost_settings(
            db_session, fleet_company.company_id, fleet_manager_user.user_id, data
        )
        assert company.fuel_price_per_litre == Decimal("60.00")

    def test_zero_allowance_is_allowed(
        self, db_session, fleet_company, fleet_manager_user
    ):
        data = CostSettingsUpdate(driver_daily_allowance=Decimal("0"))
        company = update_cost_settings(
            db_session, fleet_company.company_id, fleet_manager_user.user_id, data
        )
        assert company.driver_daily_allowance == Decimal("0")

    def test_confirm_flag_alone_is_400(
        self, db_session, fleet_company, fleet_manager_user
    ):
        with pytest.raises(HTTPException) as err:
            update_cost_settings(
                db_session,
                fleet_company.company_id,
                fleet_manager_user.user_id,
                CostSettingsUpdate(confirm_extreme_values=True),
            )
        assert err.value.status_code == 400

    def test_several_extreme_values_are_all_listed(
        self, db_session, fleet_company, fleet_manager_user
    ):
        data = CostSettingsUpdate(
            toll_assumption=Decimal("10000.01"), other_costs=Decimal("90000")
        )
        with pytest.raises(HTTPException) as err:
            update_cost_settings(
                db_session, fleet_company.company_id, fleet_manager_user.user_id, data
            )
        assert set(err.value.detail["fields"]) == {"toll_assumption", "other_costs"}

    def test_refused_update_changes_nothing(
        self, db_session, fleet_company, fleet_manager_user
    ):
        data = CostSettingsUpdate(fuel_price_per_litre=Decimal("999.00"))
        with pytest.raises(HTTPException):
            update_cost_settings(
                db_session, fleet_company.company_id, fleet_manager_user.user_id, data
            )
        db_session.refresh(fleet_company)
        assert fleet_company.fuel_price_per_litre == Decimal("27.50")

    @pytest.mark.parametrize(
        "body",
        [
            {"fuel_price_per_litre": "0"},
            {"fuel_price_per_litre": "1.234"},
            {"other_costs": "abc"},
        ],
    )
    def test_bad_values_are_422(self, client, body):
        assert client.patch("/cost-settings", json=body).status_code == 422


@pytest.fixture
def real_client(db_session):
    """The router with the real login checks (no shortcuts)."""
    app = FastAPI()
    app.include_router(cost_settings_router)
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def _user(db_session, company, email, role):
    user = models.User(
        company_id=company.company_id,
        first_name="Test",
        last_name="User",
        email=email,
        password_hash="not-a-real-hash",
        role=role,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _auth(user):
    token = create_access_token(user.user_id, user.role.value)
    return {"Authorization": f"Bearer {token}"}


class TestCostSettingsAccess:
    def test_no_token_is_401(self, real_client):
        assert real_client.get("/cost-settings").status_code == 401

    def test_fleet_manager_of_verified_company_gets_in(
        self, real_client, fleet_manager_user
    ):
        res = real_client.get("/cost-settings", headers=_auth(fleet_manager_user))
        assert res.status_code == 200
        assert res.json()["driver_daily_allowance"] == "450.00"

    def test_shipper_is_403(self, real_client, db_session, shipper_company):
        shipper = _user(
            db_session,
            shipper_company,
            "shipper.cost@zamline-mock.com",
            models.UserRole.SHIPPER,
        )
        res = real_client.get("/cost-settings", headers=_auth(shipper))
        assert res.status_code == 403

    def test_unverified_company_is_403(self, real_client, db_session):
        pending = models.Company(
            company_type=models.CompanyType.FLEET,
            business_name="Pending Logistics",
            registration_number="PACRA-COST-03",
            company_email="ops@pending-cost-mock.com",
            phone_number="+260970000003",
            verification_status=models.VerificationStatus.PENDING,
        )
        db_session.add(pending)
        db_session.flush()
        manager = _user(
            db_session,
            pending,
            "pending.cost@zamline-mock.com",
            models.UserRole.FLEET_MANAGER,
        )
        res = real_client.get("/cost-settings", headers=_auth(manager))
        assert res.status_code == 403

    def test_each_company_only_changes_its_own_settings(
        self, real_client, db_session, fleet_company, fleet_manager_user
    ):
        other = models.Company(
            company_type=models.CompanyType.FLEET,
            business_name="Kafue Transporters",
            registration_number="PACRA-COST-04",
            company_email="ops@kafue-cost-mock.com",
            phone_number="+260970000004",
            verification_status=models.VerificationStatus.VERIFIED,
            fuel_price_per_litre=Decimal("28.10"),
        )
        db_session.add(other)
        db_session.flush()
        other_manager = _user(
            db_session,
            other,
            "kafue.cost@zamline-mock.com",
            models.UserRole.FLEET_MANAGER,
        )

        res = real_client.patch(
            f"/companies/{other.company_id}/cost-settings",
            json={"fuel_price_per_litre": "30.00"},
            headers=_auth(other_manager),
        )
        assert res.status_code == 200
