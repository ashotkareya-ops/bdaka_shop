from abc import ABC, abstractmethod

class SupplierClient(ABC):
    """Единый контракт для поставщиков. Реализуйте только разрешённый способ интеграции."""

    @abstractmethod
    async def get_catalog(self):
        raise NotImplementedError

    @abstractmethod
    async def purchase(self, supplier_product_id: str):
        raise NotImplementedError
