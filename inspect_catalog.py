
import asyncio
import json
from suppliers.sandromania.client import SandromaniaClient


async def main():
    client = SandromaniaClient()
    data = await client.get_products()

    print("\n=== СТРУКТУРА ОТВЕТА ===")
    print("Тип:", type(data).__name__)

    if isinstance(data, dict):
        print("Ключи ответа:", list(data.keys()))

        for key, value in data.items():
            if isinstance(value, list) and value:
                print(f"\n=== ПЕРВЫЙ ТОВАР ИЗ {key} ===")
                print(json.dumps(value[0], ensure_ascii=False, indent=2))
                break
            elif isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    if isinstance(nested_value, list) and nested_value:
                        print(f"\n=== ПЕРВЫЙ ТОВАР ИЗ {key}.{nested_key} ===")
                        print(json.dumps(nested_value[0], ensure_ascii=False, indent=2))
                        return
    elif isinstance(data, list) and data:
        print(json.dumps(data[0], ensure_ascii=False, indent=2))


asyncio.run(main())
