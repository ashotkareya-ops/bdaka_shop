class ManualPaymentProvider:
    """Заготовка. Платёж подтверждает администратор по данным платёжного кабинета."""
    async def create_invoice(self, user_id: int, amount: float):
        return {"status": "MANUAL_INSTRUCTIONS_REQUIRED"}

    async def verify_payment(self, external_id: str):
        return False
