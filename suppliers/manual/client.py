class ManualSupplierClient:
    """Ручная закупка: администратор получает товар вне бота и добавляет CDK через /addkey."""
    async def purchase(self, supplier_product_id: str):
        return {"status": "MANUAL_REQUIRED"}
