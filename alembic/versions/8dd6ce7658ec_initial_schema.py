from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "8dd6ce7658ec"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "companies",
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column(
            "company_type",
            sa.Enum("shipper", "fleet", name="companytype"),
            nullable=False,
        ),
        sa.Column("business_name", sa.String(length=100), nullable=False),
        sa.Column("registration_number", sa.String(length=20), nullable=False),
        sa.Column("company_email", sa.String(length=255), nullable=False),
        sa.Column("phone_number", sa.String(length=15), nullable=False),
        sa.Column(
            "verification_status",
            sa.Enum(
                "pending", "verified", "resubmit", "rejected", name="verificationstatus"
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certificate_file_url", sa.String(length=255), nullable=True),
        sa.Column("verification_failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "fuel_price_per_litre", sa.Numeric(precision=10, scale=2), nullable=True
        ),
        sa.Column(
            "driver_daily_allowance", sa.Numeric(precision=10, scale=2), nullable=True
        ),
        sa.Column(
            "toll_assumption",
            sa.Numeric(precision=10, scale=2),
            server_default="0",
            nullable=True,
        ),
        sa.Column(
            "other_costs",
            sa.Numeric(precision=10, scale=2),
            server_default="0",
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "fuel_price_per_litre > 0", name="ck_companies_fuel_price_positive"
        ),
        sa.PrimaryKeyConstraint("company_id"),
    )
    op.create_index(
        op.f("ix_companies_company_email"), "companies", ["company_email"], unique=True
    )
    op.create_index(
        op.f("ix_companies_company_id"), "companies", ["company_id"], unique=False
    )
    op.create_index(
        op.f("ix_companies_registration_number"),
        "companies",
        ["registration_number"],
        unique=True,
    )
    op.create_index(
        op.f("ix_companies_verification_status"),
        "companies",
        ["verification_status"],
        unique=False,
    )
    op.create_table(
        "trucks",
        sa.Column("truck_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("plate_number", sa.String(length=20), nullable=False),
        sa.Column("truck_type", sa.String(length=30), nullable=False),
        sa.Column(
            "body_type",
            sa.Enum(
                "flatbed",
                "box",
                "tanker",
                "refrigerated",
                "tipper",
                "container",
                name="bodytype",
            ),
            nullable=False,
        ),
        sa.Column("capacity_kg", sa.Float(), nullable=False),
        sa.Column("fuel_consumption_l_per_100km", sa.Float(), nullable=False),
        sa.Column(
            "maintenance_per_km", sa.Numeric(precision=10, scale=2), nullable=False
        ),
        sa.Column(
            "availability_status",
            sa.Enum("available", "unavailable", name="availabilitystatus"),
            server_default="available",
            nullable=False,
        ),
        sa.Column("current_location", sa.String(length=50), nullable=True),
        sa.Column("available_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("capacity_kg > 0", name="ck_trucks_capacity_positive"),
        sa.CheckConstraint(
            "fuel_consumption_l_per_100km > 0",
            name="ck_trucks_fuel_consumption_positive",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.company_id"],
        ),
        sa.PrimaryKeyConstraint("truck_id"),
    )
    op.create_index(
        "ix_trucks_availability_status", "trucks", ["availability_status"], unique=False
    )
    op.create_index("ix_trucks_body_type", "trucks", ["body_type"], unique=False)
    op.create_index(
        op.f("ix_trucks_company_id"), "trucks", ["company_id"], unique=False
    )
    op.create_index(
        op.f("ix_trucks_plate_number"), "trucks", ["plate_number"], unique=True
    )
    op.create_index(op.f("ix_trucks_truck_id"), "trucks", ["truck_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("first_name", sa.String(length=50), nullable=False),
        sa.Column("last_name", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role", sa.Enum("shipper", "fleet_manager", name="userrole"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.company_id"],
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(op.f("ix_users_company_id"), "users", ["company_id"], unique=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_user_id"), "users", ["user_id"], unique=False)
    op.create_table(
        "audit_logs",
        sa.Column("audit_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("company_id", sa.UUID(), nullable=True),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column(
            "details",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.company_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index(
        "ix_audit_logs_action_type", "audit_logs", ["action_type"], unique=False
    )
    op.create_index(
        op.f("ix_audit_logs_audit_id"), "audit_logs", ["audit_id"], unique=False
    )
    op.create_index(
        "ix_audit_logs_company_id", "audit_logs", ["company_id"], unique=False
    )
    op.create_index(
        "ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False
    )
    op.create_index(
        "ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"], unique=False
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], unique=False)
    op.create_table(
        "otp_codes",
        sa.Column("otp_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("otp_id"),
    )
    op.create_index(
        op.f("ix_otp_codes_user_id"), "otp_codes", ["user_id"], unique=False
    )
    op.create_table(
        "shipments",
        sa.Column("shipment_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("origin_address", sa.String(length=250), nullable=False),
        sa.Column(
            "origin_latitude",
            sa.Numeric(precision=9, scale=6, asdecimal=False),
            nullable=False,
        ),
        sa.Column(
            "origin_longitude",
            sa.Numeric(precision=9, scale=6, asdecimal=False),
            nullable=False,
        ),
        sa.Column("destination_address", sa.String(length=250), nullable=False),
        sa.Column(
            "destination_latitude",
            sa.Numeric(precision=9, scale=6, asdecimal=False),
            nullable=False,
        ),
        sa.Column(
            "destination_longitude",
            sa.Numeric(precision=9, scale=6, asdecimal=False),
            nullable=False,
        ),
        sa.Column("cargo_type", sa.String(length=20), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column(
            "required_body_type",
            sa.Enum(
                "flatbed",
                "box",
                "tanker",
                "refrigerated",
                "tipper",
                "container",
                name="bodytype",
            ),
            nullable=False,
        ),
        sa.Column("pickup_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("special_requirements", sa.Text(), nullable=True),
        sa.Column("proposed_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "confirmed", "cancelled", "expired", name="shipmentstatus"),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "destination_latitude BETWEEN -90 AND 90", name="ck_shipments_dest_lat"
        ),
        sa.CheckConstraint(
            "destination_longitude BETWEEN -180 AND 180", name="ck_shipments_dest_lng"
        ),
        sa.CheckConstraint(
            "origin_latitude BETWEEN -90 AND 90", name="ck_shipments_origin_lat"
        ),
        sa.CheckConstraint(
            "origin_longitude BETWEEN -180 AND 180", name="ck_shipments_origin_lng"
        ),
        sa.CheckConstraint("proposed_amount > 0", name="ck_shipments_amount_positive"),
        sa.CheckConstraint("weight_kg > 0", name="ck_shipments_weight_positive"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.company_id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
        ),
        sa.PrimaryKeyConstraint("shipment_id"),
    )
    op.create_index(
        op.f("ix_shipments_company_id"), "shipments", ["company_id"], unique=False
    )
    op.create_index(
        "ix_shipments_required_body_type",
        "shipments",
        ["required_body_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shipments_shipment_id"), "shipments", ["shipment_id"], unique=False
    )
    op.create_index("ix_shipments_status", "shipments", ["status"], unique=False)
    op.create_index(
        op.f("ix_shipments_user_id"), "shipments", ["user_id"], unique=False
    )
    op.create_table(
        "shipment_matches",
        sa.Column("match_id", sa.UUID(), nullable=False),
        sa.Column("shipment_id", sa.UUID(), nullable=False),
        sa.Column("truck_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("fuel_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("driver_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("toll_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("maintenance_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("other_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "estimated_total_cost", sa.Numeric(precision=12, scale=2), nullable=True
        ),
        sa.Column("proposed_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("estimated_margin", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum("profit", "loss", "break_even", name="matchoutcome"),
            nullable=True,
        ),
        sa.Column("ai_explanation", sa.Text(), nullable=True),
        sa.Column(
            "manager_decision",
            sa.Enum(
                "pending", "accepted", "declined", "closed", name="managerdecision"
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.shipment_id"],
        ),
        sa.ForeignKeyConstraint(
            ["truck_id"],
            ["trucks.truck_id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
        ),
        sa.PrimaryKeyConstraint("match_id"),
        sa.UniqueConstraint(
            "shipment_id", "truck_id", name="uq_shipment_matches_shipment_truck"
        ),
    )
    op.create_index(
        "ix_shipment_matches_manager_decision",
        "shipment_matches",
        ["manager_decision"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shipment_matches_match_id"),
        "shipment_matches",
        ["match_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shipment_matches_shipment_id"),
        "shipment_matches",
        ["shipment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shipment_matches_truck_id"),
        "shipment_matches",
        ["truck_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shipment_matches_user_id"),
        "shipment_matches",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "reservations",
        sa.Column("reservation_id", sa.UUID(), nullable=False),
        sa.Column("shipment_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("truck_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("match_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("accepted", "cancelled", name="reservationstatus"),
            server_default="accepted",
            nullable=False,
        ),
        sa.Column(
            "reserved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.company_id"],
        ),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["shipment_matches.match_id"],
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["shipments.shipment_id"],
        ),
        sa.ForeignKeyConstraint(
            ["truck_id"],
            ["trucks.truck_id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
        ),
        sa.PrimaryKeyConstraint("reservation_id"),
        sa.UniqueConstraint("match_id"),
    )
    op.create_index(
        op.f("ix_reservations_company_id"), "reservations", ["company_id"], unique=False
    )
    op.create_index(
        op.f("ix_reservations_reservation_id"),
        "reservations",
        ["reservation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reservations_shipment_id"),
        "reservations",
        ["shipment_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_reservations_truck_id"), "reservations", ["truck_id"], unique=False
    )
    op.create_index(
        op.f("ix_reservations_user_id"), "reservations", ["user_id"], unique=False
    )


def downgrade() -> None:

    op.drop_index(op.f("ix_reservations_user_id"), table_name="reservations")
    op.drop_index(op.f("ix_reservations_truck_id"), table_name="reservations")
    op.drop_index(op.f("ix_reservations_shipment_id"), table_name="reservations")
    op.drop_index(op.f("ix_reservations_reservation_id"), table_name="reservations")
    op.drop_index(op.f("ix_reservations_company_id"), table_name="reservations")
    op.drop_table("reservations")
    op.drop_index(op.f("ix_shipment_matches_user_id"), table_name="shipment_matches")
    op.drop_index(op.f("ix_shipment_matches_truck_id"), table_name="shipment_matches")
    op.drop_index(
        op.f("ix_shipment_matches_shipment_id"), table_name="shipment_matches"
    )
    op.drop_index(op.f("ix_shipment_matches_match_id"), table_name="shipment_matches")
    op.drop_index("ix_shipment_matches_manager_decision", table_name="shipment_matches")
    op.drop_table("shipment_matches")
    op.drop_index(op.f("ix_shipments_user_id"), table_name="shipments")
    op.drop_index("ix_shipments_status", table_name="shipments")
    op.drop_index(op.f("ix_shipments_shipment_id"), table_name="shipments")
    op.drop_index("ix_shipments_required_body_type", table_name="shipments")
    op.drop_index(op.f("ix_shipments_company_id"), table_name="shipments")
    op.drop_table("shipments")
    op.drop_index(op.f("ix_otp_codes_user_id"), table_name="otp_codes")
    op.drop_table("otp_codes")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_company_id", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_audit_id"), table_name="audit_logs")
    op.drop_index("ix_audit_logs_action_type", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_users_user_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_company_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_trucks_truck_id"), table_name="trucks")
    op.drop_index(op.f("ix_trucks_plate_number"), table_name="trucks")
    op.drop_index(op.f("ix_trucks_company_id"), table_name="trucks")
    op.drop_index("ix_trucks_body_type", table_name="trucks")
    op.drop_index("ix_trucks_availability_status", table_name="trucks")
    op.drop_table("trucks")
    op.drop_index(op.f("ix_companies_verification_status"), table_name="companies")
    op.drop_index(op.f("ix_companies_registration_number"), table_name="companies")
    op.drop_index(op.f("ix_companies_company_id"), table_name="companies")
    op.drop_index(op.f("ix_companies_company_email"), table_name="companies")
    op.drop_table("companies")
