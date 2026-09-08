"""add google sign-in support

Revision ID: b2c7c884f567
Revises: de243357a7fa
Create Date: 2026-09-08 06:30:48.237462

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


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

    ملاحظتان إضافيتان (اكتُشفتا فعليًا من مستخدم حقيقي على Windows):

    1) وضع add_column وalter_column وcreate_index في نفس كتلة
       batch_alter_table واحدة قد يُطلق CircularDependencyError (خطأ
       Alembic معروف، غير حتمي، يعتمد على ترتيب أعمدة قاعدة بيانات
       المستخدم) — الحل: كتلة batch منفصلة لكل عملية (مُطبَّق أدناه).

    2) SQLite ينفّذ كل عبارة DDL فور استدعائها (وليس ضمن معاملة تُلغى
       بالكامل عند الفشل، كما لاحظ Alembic نفسه في اللوغ:
       "Will assume non-transactional DDL") — فإذا فشلت الترقية في
       منتصفها (كما حدث بسبب المشكلة رقم 1 أعلاه)، قد يكون العمود أُضيف
       فعليًا على القرص رغم أن Alembic لا يزال يعتبر الترحيل غير مكتمل.
       إعادة المحاولة حينها تفشل بـ"duplicate column name". الحل: نجعل
       كل خطوة هنا **Idempotent** — تتحقق أولًا من الحالة الفعلية على
       القرص (عبر inspect) قبل تنفيذ أي تغيير، فتكون آمنة للتكرار من أي
       نقطة توقّف سابقة دون أي تدخّل يدوي من المستخدم.
    """
    conn = op.get_bind()

    existing_columns = {c["name"] for c in inspect(conn).get_columns("users")}
    if "google_id" not in existing_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(sa.Column("google_id", sa.String(length=255), nullable=True))

    hashed_password_col = next(
        (c for c in inspect(conn).get_columns("users") if c["name"] == "hashed_password"), None
    )
    if hashed_password_col is not None and not hashed_password_col["nullable"]:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.alter_column(
                "hashed_password", existing_type=sa.VARCHAR(length=255), nullable=True
            )

    existing_indexes = {idx["name"] for idx in inspect(conn).get_indexes("users")}
    index_name = "ix_users_google_id"
    if index_name not in existing_indexes:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.create_index(batch_op.f(index_name), ["google_id"], unique=True)


def downgrade() -> None:
    """Downgrade schema. نفس منطق التحقق قبل التنفيذ (Idempotent) بالاتجاه المعاكس."""
    conn = op.get_bind()

    existing_indexes = {idx["name"] for idx in inspect(conn).get_indexes("users")}
    index_name = "ix_users_google_id"
    if index_name in existing_indexes:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_index(batch_op.f(index_name))

    hashed_password_col = next(
        (c for c in inspect(conn).get_columns("users") if c["name"] == "hashed_password"), None
    )
    if hashed_password_col is not None and hashed_password_col["nullable"]:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.alter_column(
                "hashed_password", existing_type=sa.VARCHAR(length=255), nullable=False
            )

    existing_columns = {c["name"] for c in inspect(conn).get_columns("users")}
    if "google_id" in existing_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("google_id")
