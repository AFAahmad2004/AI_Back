"""add google sign-in support

Revision ID: b2c7c884f567
Revises: de243357a7fa
Create Date: 2026-09-08 06:30:48.237462

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c7c884f567'
down_revision: Union[str, Sequence[str], None] = 'de243357a7fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    ملاحظة مهمة (اكتُشفت فعليًا أثناء الاختبار): SQLite لا يدعم
    `ALTER COLUMN ... DROP NOT NULL` مباشرة (خلافًا لـ PostgreSQL الذي
    يدعمه بلا مشاكل) — يرمي خطأ SQL صريحًا. الحل الموصى به رسميًا من
    Alembic لهذه الحالة هو batch_alter_table، الذي يعيد إنشاء الجدول
    بالمخطط الجديد وينسخ البيانات إليه تلقائيًا، ويعمل بشكل صحيح على
    SQLite وPostgreSQL معًا دون فرع كود منفصل لكل قاعدة بيانات.
    """
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('google_id', sa.String(length=255), nullable=True))
        batch_op.alter_column('hashed_password',
                               existing_type=sa.VARCHAR(length=255),
                               nullable=True)
        batch_op.create_index(batch_op.f('ix_users_google_id'), ['google_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_google_id'))
        batch_op.alter_column('hashed_password',
                               existing_type=sa.VARCHAR(length=255),
                               nullable=False)
        batch_op.drop_column('google_id')
