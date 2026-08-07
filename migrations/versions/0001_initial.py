"""initial schema"""
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pipeline_version", sa.String(20), nullable=True),
        sa.Column("source_kind", sa.String(20), nullable=False, server_default="real"),
    )
    op.create_table(
        "track_analyses",
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("channels", sa.Integer(), nullable=False),
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("bpm_confidence", sa.Float(), nullable=True),
        sa.Column("key_tonic", sa.String(10), nullable=True),
        sa.Column("mode", sa.String(10), nullable=True),
        sa.Column("key_confidence", sa.Float(), nullable=True),
        sa.Column("time_signature", sa.String(10), nullable=True),
        sa.Column("time_signature_confidence", sa.Float(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "section_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("algorithm", sa.String(50), nullable=False),
    )
    op.create_table(
        "chord_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("algorithm", sa.String(50), nullable=False),
        sa.Column("theory_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "time_series",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("resolution_seconds", sa.Float(), nullable=False),
        sa.Column("points_json", sa.Text(), nullable=False),
        sa.Column("algorithm", sa.String(50), nullable=False),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("algorithm", sa.String(50), nullable=False),
        sa.Column("eligible_for_llm", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.create_table(
        "explanations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("segment_start", sa.Float(), nullable=False),
        sa.Column("segment_end", sa.Float(), nullable=False),
        sa.Column("question_digest", sa.String(64), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("explanations")
    op.drop_table("evidence")
    op.drop_table("time_series")
    op.drop_table("chord_events")
    op.drop_table("section_events")
    op.drop_table("track_analyses")
    op.drop_table("analysis_jobs")