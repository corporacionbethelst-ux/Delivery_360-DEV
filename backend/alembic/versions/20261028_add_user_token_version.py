"""Persist account credential epochs for JWT revocation.

Apply before deploying consumers of users.token_version. Existing JWTs without
ver remain epoch zero and cannot authenticate after that account is revoked.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261028_auth_version"
down_revision = "20260930_fase10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        "ck_users_token_version_nonnegative", "users", "token_version >= 0"
    )


def downgrade() -> None:
    # Dropping an epoch after any revocation would resurrect old signed JWTs
    # on a subsequent upgrade. Refuse that unsafe rollback automatically.
    op.get_bind().execute(sa.text("LOCK TABLE users IN ACCESS EXCLUSIVE MODE"))
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM users WHERE token_version <> 0 LIMIT 1"))
        .first()
    ):
        raise RuntimeError(
            "Cannot remove credential epochs after revocation; rotate JWT signing keys and plan an explicit security rollback"
        )
    op.drop_constraint("ck_users_token_version_nonnegative", "users", type_="check")
    op.drop_column("users", "token_version")
