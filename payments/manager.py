class PaymentManager:
    def __init__(self):
        self.providers = {}

    def register(self, name, provider):
        self.providers[name] = provider

    def get(self, name):
        if name not in self.providers:
            raise ValueError(f"Payment provider not configured: {name}")
        return self.providers[name]
