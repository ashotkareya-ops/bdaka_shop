from abc import ABC, abstractmethod

class PaymentProvider(ABC):
    @abstractmethod
    async def create_invoice(self, user_id: int, amount: float):
        raise NotImplementedError

    @abstractmethod
    async def verify_payment(self, external_id: str):
        raise NotImplementedError
