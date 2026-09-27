"""Fictional shop layouts and item pools for the synthetic receipt generator.

All names, addresses and products are invented for this demo. Any
resemblance to a real business is coincidental.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShopLayout:
    key: str
    name: str
    address: str
    currency: str  # ISO 4217 code this shop always prints
    symbol: str  # the symbol/code this shop's receipts render on the total line
    width_px: int
    font_style: str  # "mono" or "sans" -- picks the rendering font
    align: str  # "left" or "center" for the item block
    footer: str
    catalog: tuple[tuple[str, float], ...]  # (item name, unit price)


CATALOGS = {
    "grocery": (
        ("Oat Milk 1L", 2.49),
        ("Sourdough Loaf", 3.20),
        ("Free Range Eggs 12ct", 4.10),
        ("Roma Tomatoes 1kg", 1.85),
        ("Cheddar Block 200g", 3.75),
        ("Basmati Rice 2kg", 5.60),
        ("Olive Oil 500ml", 6.99),
        ("Bananas 1kg", 0.95),
        ("Greek Yogurt 500g", 2.30),
        ("Chicken Breast 500g", 4.85),
    ),
    "cafe": (
        ("Flat White", 3.60),
        ("Espresso", 2.40),
        ("Almond Croissant", 3.10),
        ("Avocado Toast", 7.50),
        ("Iced Latte", 4.20),
        ("Blueberry Muffin", 2.90),
        ("Chai Tea", 3.30),
        ("Bagel & Cream Cheese", 4.60),
    ),
    "superstore": (
        ("AA Batteries 4pk", 3.99),
        ("USB-C Cable 1m", 6.49),
        ("Kitchen Sponge 3pk", 1.99),
        ("Notebook A5", 2.75),
        ("Dish Soap 750ml", 2.60),
        ("LED Bulb 9W", 3.20),
        ("Paper Towels 2pk", 2.99),
        ("Laundry Pods 20ct", 8.40),
        ("Extension Cord 3m", 7.20),
    ),
    "bookshop": (
        ("Paperback Novel", 9.99),
        ("Notebook, Ruled", 4.50),
        ("Fountain Pen", 12.00),
        ("Bookmark Set", 2.20),
        ("Poetry Collection", 8.75),
        ("Graphic Novel", 14.50),
        ("Desk Calendar", 6.30),
    ),
}

SHOP_LAYOUTS: tuple[ShopLayout, ...] = (
    ShopLayout(
        key="corner_grocery",
        name="Corner Grocery",
        address="14 Maple Street",
        currency="USD",
        symbol="$",
        width_px=380,
        font_style="mono",
        align="left",
        footer="Thank you for shopping with us",
        catalog=CATALOGS["grocery"],
    ),
    ShopLayout(
        key="riverside_cafe",
        name="Riverside Cafe",
        address="2 Bridge Lane",
        currency="EUR",
        symbol="EUR",
        width_px=420,
        font_style="sans",
        align="center",
        footer="See you again soon",
        catalog=CATALOGS["cafe"],
    ),
    ShopLayout(
        key="brightmart",
        name="BrightMart Superstore",
        address="Unit 4, Retail Park North",
        currency="GBP",
        symbol="GBP",
        width_px=460,
        font_style="mono",
        align="left",
        footer="Returns within 30 days with receipt",
        catalog=CATALOGS["superstore"],
    ),
    ShopLayout(
        key="luna_bookshop",
        name="Luna Bookshop",
        address="9 Harbour Row",
        currency="USD",
        symbol="$",
        width_px=400,
        font_style="sans",
        align="left",
        footer="Read something new today",
        catalog=CATALOGS["bookshop"],
    ),
)

SHOP_BY_KEY = {s.key: s for s in SHOP_LAYOUTS}
