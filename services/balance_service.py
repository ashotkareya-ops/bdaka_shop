from database.models.transaction import Transaction

async def add_balance(session, user, amount, description, transaction_type="TOPUP"):
    if amount <= 0:
        raise ValueError("amount must be positive")
    user.balance += amount
    session.add(Transaction(user_id=user.id, amount=amount, type=transaction_type,
                            description=description))
