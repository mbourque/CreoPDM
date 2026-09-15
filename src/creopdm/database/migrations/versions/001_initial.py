"""Initial PDM schema.

Revision ID: 001_initial
Revises:
Create Date: 2026-09-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("repository_path", sa.String(length=1024), nullable=False),
        sa.Column("default_branch", sa.String(length=128), nullable=False, server_default="main"),
        sa.Column("remote_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index("ix_projects_uuid", "projects", ["uuid"])

    op.create_table(
        "objects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("extension", sa.String(length=32), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("relative_path", sa.String(length=1024), nullable=False),
        sa.Column("revision", sa.String(length=16), nullable=False, server_default="A"),
        sa.Column("iteration", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("lifecycle_state", sa.String(length=32), nullable=False, server_default="IN_WORK"),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("uuid"),
        sa.UniqueConstraint("project_id", "relative_path", name="uq_objects_project_path"),
    )
    op.create_index("ix_objects_uuid", "objects", ["uuid"])
    op.create_index("ix_objects_project_id", "objects", ["project_id"])

    op.create_table(
        "object_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("object_id", sa.Integer(), sa.ForeignKey("objects.id"), nullable=False),
        sa.Column("revision", sa.String(length=16), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("git_commit_hash", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.UniqueConstraint("uuid"),
    )
    op.create_index("ix_object_versions_uuid", "object_versions", ["uuid"])
    op.create_index("ix_object_versions_object_id", "object_versions", ["object_id"])

    with op.batch_alter_table("objects") as batch_op:
        batch_op.create_foreign_key(
            "fk_objects_current_version",
            "object_versions",
            ["current_version_id"],
            ["id"],
        )

    op.create_table(
        "dependencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("parent_object_id", sa.Integer(), sa.ForeignKey("objects.id"), nullable=False),
        sa.Column("child_object_id", sa.Integer(), sa.ForeignKey("objects.id"), nullable=False),
        sa.Column("dependency_type", sa.String(length=32), nullable=False, server_default="ASSEMBLY_MEMBER"),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "project_id",
            "parent_object_id",
            "child_object_id",
            "dependency_type",
            name="uq_dependencies_edge",
        ),
    )
    op.create_index("ix_dependencies_project_id", "dependencies", ["project_id"])
    op.create_index("ix_dependencies_parent_object_id", "dependencies", ["parent_object_id"])
    op.create_index("ix_dependencies_child_object_id", "dependencies", ["child_object_id"])

    op.create_table(
        "parameters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("object_id", sa.Integer(), sa.ForeignKey("objects.id"), nullable=False),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("object_versions.id"), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("data_type", sa.String(length=32), nullable=False, server_default="STRING"),
        sa.Column("units", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_parameters_object_id", "parameters", ["object_id"])
    op.create_index("ix_parameters_version_id", "parameters", ["version_id"])

    op.create_table(
        "checkouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("object_id", sa.Integer(), sa.ForeignKey("objects.id"), nullable=False),
        sa.Column("user_name", sa.String(length=128), nullable=False),
        sa.Column("machine_name", sa.String(length=128), nullable=False),
        sa.Column("workspace_path", sa.String(length=1024), nullable=False),
        sa.Column("checkout_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("heartbeat_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
    )
    op.create_index("ix_checkouts_object_id", "checkouts", ["object_id"])
    op.create_index("ix_checkouts_status", "checkouts", ["status"])
    op.execute(
        "CREATE UNIQUE INDEX uq_checkouts_object_active "
        "ON checkouts(object_id) WHERE status = 'ACTIVE'"
    )

    op.create_table(
        "activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("object_id", sa.Integer(), sa.ForeignKey("objects.id"), nullable=True),
        sa.Column("user", sa.String(length=128), nullable=False),
        sa.Column("machine", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("details_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_activities_project_id", "activities", ["project_id"])
    op.create_index("ix_activities_object_id", "activities", ["object_id"])
    op.create_index("ix_activities_action", "activities", ["action"])

    op.create_table(
        "remotes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False, server_default="origin"),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="generic"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_remotes_project_id", "remotes", ["project_id"])


def downgrade() -> None:
    op.drop_table("remotes")
    op.drop_table("activities")
    op.drop_table("checkouts")
    op.drop_table("parameters")
    op.drop_table("dependencies")
    op.drop_constraint("fk_objects_current_version", "objects", type_="foreignkey")
    op.drop_table("object_versions")
    op.drop_table("objects")
    op.drop_table("projects")
