from suppliers.sandromania.client import SandromaniaClient

class SupplierManager:
    def __init__(self):
        self.clients = {"sandromania": SandromaniaClient()}

    def get(self, name):
        client = self.clients.get(name)
        if client is None:
            raise ValueError(f"Unknown supplier: {name}")
        return client
