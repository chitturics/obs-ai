"""Initial schema — matches init_schema.py tables.

Revision ID: 001_initial
Revises: None
Create Date: 2026-03-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Chainlit core tables ---

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("identifier", sa.Text(), nullable=False, unique=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("createdAt", sa.Text()),
    )

    op.create_table(
        "threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("createdAt", sa.Text()),
        sa.Column("name", sa.Text()),
        sa.Column("userId", postgresql.UUID(as_uuid=True)),
        sa.Column("userIdentifier", sa.Text()),
        sa.Column("tags", postgresql.ARRAY(sa.Text())),
        sa.Column("metadata", postgresql.JSONB()),
        sa.ForeignKeyConstraint(["userId"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("threadId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parentId", postgresql.UUID(as_uuid=True)),
        sa.Column("streaming", sa.Boolean(), nullable=False),
        sa.Column("waitForAnswer", sa.Boolean()),
        sa.Column("isError", sa.Boolean()),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("tags", postgresql.ARRAY(sa.Text())),
        sa.Column("input", sa.Text()),
        sa.Column("output", sa.Text()),
        sa.Column("createdAt", sa.Text()),
        sa.Column("command", sa.Text()),
        sa.Column("start", sa.Text()),
        sa.Column("end", sa.Text()),
        sa.Column("generation", postgresql.JSONB()),
        sa.Column("showInput", sa.Text()),
        sa.Column("language", sa.Text()),
        sa.Column("indent", sa.Integer()),
        sa.Column("defaultOpen", sa.Boolean()),
        sa.ForeignKeyConstraint(["threadId"], ["threads.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "elements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("threadId", postgresql.UUID(as_uuid=True)),
        sa.Column("type", sa.Text()),
        sa.Column("url", sa.Text()),
        sa.Column("chainlitKey", sa.Text()),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display", sa.Text()),
        sa.Column("objectKey", sa.Text()),
        sa.Column("size", sa.Text()),
        sa.Column("page", sa.Integer()),
        sa.Column("language", sa.Text()),
        sa.Column("forId", postgresql.UUID(as_uuid=True)),
        sa.Column("mime", sa.Text()),
        sa.Column("props", postgresql.JSONB()),
        sa.Column("content", sa.LargeBinary()),
        sa.ForeignKeyConstraint(["threadId"], ["threads.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "feedbacks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("forId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("threadId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text()),
        sa.ForeignKeyConstraint(["threadId"], ["threads.id"], ondelete="CASCADE"),
    )

    # --- Blobs ---

    op.create_table(
        "blobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("mime", sa.Text()),
        sa.Column("size", sa.Integer()),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_blobs_key", "blobs", ["key"])

    # --- Application-specific tables ---

    op.create_table(
        "assistant_interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text()),
        sa.Column("question", sa.Text()),
        sa.Column("answer", sa.Text()),
        sa.Column("context", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "assistant_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", sa.Text()),
        sa.Column("value", sa.Integer()),
        sa.Column("comment", sa.Text()),
        sa.Column("username", sa.Text()),
        sa.Column("thread_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "assistant_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text()),
        sa.Column("body", sa.Text()),
        sa.Column("created_by", sa.Text()),
        sa.Column("thread_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "assistant_doc_ingests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.Text()),
        sa.Column("thread_id", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("kind", sa.Text()),
        sa.Column("fingerprint", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "assistant_liked_queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.Text()),
        sa.Column("thread_id", sa.Text()),
        sa.Column("question", sa.Text()),
        sa.Column("answer", sa.Text()),
        sa.Column("context", sa.Text()),
        sa.Column("source_message_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "assistant_disliked_queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.Text()),
        sa.Column("thread_id", sa.Text()),
        sa.Column("question", sa.Text()),
        sa.Column("answer", sa.Text()),
        sa.Column("context", sa.Text()),
        sa.Column("source_message_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "assistant_mcp_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("server_name", sa.Text(), nullable=False),
        sa.Column("auth_scheme", sa.Text(), server_default="none"),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("user_id", "server_name"),
    )

    op.create_table(
        "assistant_episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(50)),
        sa.Column("profile", sa.String(50)),
        sa.Column("strategy_used", sa.String(100)),
        sa.Column("collections_searched", sa.Text()),
        sa.Column("chunks_found", sa.Integer(), server_default="0"),
        sa.Column("response_length", sa.Integer(), server_default="0"),
        sa.Column("confidence", sa.Float(), server_default="0.0"),
        sa.Column("success", sa.Integer(), server_default="-1"),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("duration_ms", sa.Integer(), server_default="0"),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_episodes_query_hash", "assistant_episodes", ["query_hash"])
    op.create_index("idx_episodes_username", "assistant_episodes", ["username"])
    op.create_index("idx_episodes_intent", "assistant_episodes", ["intent"])

    op.create_table(
        "assistant_semantic_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pattern_hash", sa.String(64), unique=True),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("category", sa.String(50)),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("times_applied", sa.Integer(), server_default="0"),
        sa.Column("times_succeeded", sa.Integer(), server_default="0"),
        sa.Column("source_episodes", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("assistant_semantic_facts")
    op.drop_table("assistant_episodes")
    op.drop_table("assistant_mcp_tokens")
    op.drop_table("assistant_disliked_queries")
    op.drop_table("assistant_liked_queries")
    op.drop_table("assistant_doc_ingests")
    op.drop_table("assistant_notes")
    op.drop_table("assistant_feedback")
    op.drop_table("assistant_interactions")
    op.drop_table("blobs")
    op.drop_table("feedbacks")
    op.drop_table("elements")
    op.drop_table("steps")
    op.drop_table("threads")
    op.drop_table("users")
