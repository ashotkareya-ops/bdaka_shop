def calculate_price(base_price: float, markup: float = 0.0) -> float:
    if base_price < 0 or markup < 0:
        raise ValueError("Price and markup cannot be negative")
    return round(base_price + markup, 2)
