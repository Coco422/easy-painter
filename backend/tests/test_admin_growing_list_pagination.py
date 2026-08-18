from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import admin_routes
from app.db.base import Base
from app.models.credit_transaction import CreditTransaction, CreditTransactionType
from app.models.redemption_code import RedemptionCode
from app.models.user import User
from app.models.user_group import UserGroup


def make_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_users_codes_and_transactions_return_totaled_pages():
    db = make_session()
    now = datetime.now(timezone.utc)
    db.add(UserGroup(code="standard", name="普通用户", is_default=True))
    users = [
        User(
            id=f"user-{index}",
            username=f"member-{index}",
            display_name=f"成员 {index}",
            password_hash="hash",
            group_code="standard",
            created_at=now + timedelta(minutes=index),
        )
        for index in range(4)
    ]
    db.add_all(users)
    db.add_all([
        RedemptionCode(
            id=f"code-{index}",
            code=f"CODE-{index}",
            credits=10,
            created_by=users[0].id,
            used_by=users[1].id if index == 3 else None,
            created_at=now + timedelta(minutes=index),
        )
        for index in range(4)
    ])
    db.add_all([
        CreditTransaction(
            id=f"transaction-{index}",
            user_id=users[index % 2].id,
            amount=index + 1,
            balance_after=index + 1,
            reason="test",
            transaction_type=CreditTransactionType.ADMIN_ADJUST,
            created_at=now + timedelta(minutes=index),
        )
        for index in range(5)
    ])
    db.commit()

    user_page = admin_routes.admin_list_users(
        db=db, _={}, page=2, page_size=2, q="member", group_code="standard"
    )
    assert user_page.total == 4
    assert [item.username for item in user_page.items] == ["member-1", "member-0"]

    unused_codes = admin_routes.admin_list_codes(
        status_filter="unused", page=2, page_size=2, db=db, _={}
    )
    assert unused_codes.total == 3
    assert [item.id for item in unused_codes.items] == ["code-0"]

    transaction_page = admin_routes.admin_list_transactions(
        user_id=users[0].id, page=1, page_size=2, db=db, _={}
    )
    assert transaction_page.total == 3
    assert len(transaction_page.items) == 2
    assert all(item.user_id == users[0].id for item in transaction_page.items)
