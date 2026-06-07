"""Esquema inicial EEW con PostGIS

Revision ID: 001
Revises:
Create Date: 2026-06-05

"""
from typing import Sequence, Union

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("api_key_hash", sa.String(length=128), nullable=False),
        sa.Column("auth_tier", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )
    op.create_index("ix_clients_client_id", "clients", ["client_id"], unique=False)

    op.create_table(
        "seismic_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("epicenter", geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326), nullable=False),
        sa.Column("magnitude", sa.Float(), nullable=False),
        sa.Column("depth_km", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_seismic_events_event_id", "seismic_events", ["event_id"], unique=False)

    op.create_table(
        "client_locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("coordinates", geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326), nullable=False),
        sa.Column("radius_km", sa.Float(), nullable=True),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_client_locations_client_id", "client_locations", ["client_id"], unique=False)

    op.create_table(
        "alert_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("dispatched_at_utc", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("calculated_eta_s_wave", sa.Float(), nullable=False),
        sa.Column("delivery_status", sa.String(length=32), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["seismic_events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_logs_client_id", "alert_logs", ["client_id"], unique=False)
    op.create_index("ix_alert_logs_event_id", "alert_logs", ["event_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alert_logs_event_id", table_name="alert_logs")
    op.drop_index("ix_alert_logs_client_id", table_name="alert_logs")
    op.drop_table("alert_logs")
    op.drop_index("ix_client_locations_client_id", table_name="client_locations")
    op.drop_table("client_locations")
    op.drop_index("ix_seismic_events_event_id", table_name="seismic_events")
    op.drop_table("seismic_events")
    op.drop_index("ix_clients_client_id", table_name="clients")
    op.drop_table("clients")
