"""Satis danismani agent'i icin MCP sunucusu.

Veri kaynagi: SQLite `data.db` -> Prisma (model Order).
Tum tool'lar salt-okunur ve yalnizca Prisma ORM API'sini kullanir (raw SQL yok).
"""

import asyncio
import json
from typing import Any, Literal

from dotenv import load_dotenv
from fastmcp import FastMCP
from mcp.types import TextContent
from prisma import Prisma
from prisma.types import OrderWhereInput

load_dotenv()

mcp = FastMCP(name="sales-db")

db = Prisma()
_lock = asyncio.Lock()

CategoryName = Literal[
    "Automotive",
    "Baby Products",
    "Beauty",
    "Books",
    "Clothing",
    "Electronics",
    "Footwear",
    "Furniture",
    "Gardening",
    "Grocery",
    "Health",
    "Home & Kitchen",
    "Jewelry",
    "Music",
    "Office Supplies",
    "Pet Supplies",
    "Sports",
    "Tools & Hardware",
    "Toys",
    "Travel Accessories",
]

PaymentMethod = Literal[
    "Credit Card",
    "Debit Card",
    "Cash on Delivery",
    "Bank Transfer",
    "PayPal",
]


async def get_db() -> Prisma:
    """Ilk tool cagrisinda baglanir, sonrasinda ayni baglantiyi kullanir."""
    if not db.is_connected():
        async with _lock:
            if not db.is_connected():
                await db.connect()
    return db


def _money(value: float) -> float:
    return round(value, 2)


async def _resolve_product(client: Prisma, name: str) -> str | None:
    """Kullanicinin yazdigi urun adini katalogdaki gercek yazimina cevirir."""
    target = name.strip().lower()
    groups = await client.order.group_by(["product"])
    for g in groups:
        prod = g["product"]
        prod_lower = prod.lower()
        if prod_lower == target or target in prod_lower or prod_lower in target:
            return prod
    return None


async def _product_stats(
    client: Prisma, where: OrderWhereInput | None = None
) -> list[dict[str, Any]]:
    """Urun bazinda fiyat/satis ozetini dondurur (ciro'ya gore sirali degil)."""
    groups = await client.order.group_by(
        ["product", "category"],
        where=where,
        count=True,
        avg={"unitPrice": True},
        min={"unitPrice": True},
        max={"unitPrice": True},
        sum={"quantity": True, "totalPrice": True},
    )
    return [
        {
            "product": g["product"],
            "category": g["category"],
            "avg_price": _money(g["_avg"]["unitPrice"]),
            "price_range": [
                _money(g["_min"]["unitPrice"]),
                _money(g["_max"]["unitPrice"]),
            ],
            "units_sold": g["_sum"]["quantity"],
            "revenue": _money(g["_sum"]["totalPrice"]),
            "order_count": g["_count"]["_all"],
        }
        for g in groups
    ]


@mcp.tool
async def list_categories() -> list[TextContent]:
    """Urun kategorilerini, urun cesit sayilarini (product_count) ve ortalama fiyatlarini listeler."""
    
    client = await get_db()
    groups = await client.order.group_by(
        ["category", "product"],
        count=True,
        avg={"unitPrice": True},
    )

    folded: dict[str, dict[str, float]] = {}
    for g in groups:
        acc = folded.setdefault(
            g["category"], {"product_count": 0, "order_count": 0, "price_sum": 0.0}
        )
        count = g["_count"]["_all"]
        acc["product_count"] += 1
        acc["order_count"] += count
        acc["price_sum"] += g["_avg"]["unitPrice"] * count

    res = [
        {
            "category": category,
            "product_count": int(acc["product_count"]),
            "order_count": int(acc["order_count"]),
            "avg_unit_price": _money(acc["price_sum"] / acc["order_count"]),
        }
        for category, acc in sorted(folded.items())
    ]
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]


@mcp.tool
async def search_products(
    query: str | None = None,
    category: CategoryName | None = None,
    payment_method: PaymentMethod | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 20,
) -> list[TextContent]:
    """Urun veya kategoride kelime/butce aramasi yapar."""
    client = await get_db()

    filters: list[OrderWhereInput] = []
    if query:
        filters.append(
            {"OR": [{"product": {"contains": query}}, {"category": {"contains": query}}]}
        )
    if category:
        filters.append({"category": {"equals": category}})
    if payment_method:
        filters.append({"paymentMethod": {"equals": payment_method}})

    where: OrderWhereInput | None = {"AND": filters} if filters else None
    stats = await _product_stats(client, where)

    if min_price is not None:
        stats = [r for r in stats if r["avg_price"] >= min_price]
    if max_price is not None:
        stats = [r for r in stats if r["avg_price"] <= max_price]

    stats.sort(key=lambda r: r["units_sold"], reverse=True)
    res = [
        {k: v for k, v in r.items() if k not in ("revenue", "order_count")}
        for r in stats[:limit]
    ]
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]


@mcp.tool
async def get_product_details(product: str) -> list[TextContent]:
    """Tek bir urunun detayli fiyat, satis, sehir ve odeme bilgilerini verir."""
    client = await get_db()

    name = await _resolve_product(client, product)
    if name is None:
        return [TextContent(type="text", text=json.dumps({"found": False, "message": f"'{product}' adinda bir urun katalogda yok."}, ensure_ascii=False))]

    where: OrderWhereInput = {"product": {"equals": name}}
    stats = (await _product_stats(client, where))[0]

    city_groups = await client.order.group_by(
        ["customerCity"], where=where, sum={"quantity": True}
    )
    cities = sorted(
        ({"city": g["customerCity"], "units": g["_sum"]["quantity"]} for g in city_groups),
        key=lambda c: c["units"],
        reverse=True,
    )[:5]

    payment_groups = await client.order.group_by(
        ["paymentMethod"], where=where, count=True
    )
    payments = sorted(
        (
            {"method": g["paymentMethod"], "count": g["_count"]["_all"]}
            for g in payment_groups
        ),
        key=lambda p: p["count"],
        reverse=True,
    )

    res = {
        "found": True,
        "product": stats["product"],
        "category": stats["category"],
        "avg_price": stats["avg_price"],
        "price_range": stats["price_range"],
        "order_count": stats["order_count"],
        "units_sold": stats["units_sold"],
        "revenue": stats["revenue"],
        "avg_quantity_per_order": round(stats["units_sold"] / stats["order_count"], 2),
        "top_cities": cities,
        "payment_methods": payments,
    }
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]


@mcp.tool
async def top_products(
    category: CategoryName | None = None,
    metric: Literal["units", "revenue"] = "units",
    limit: int = 10,
) -> list[TextContent]:
    """En cok satan (units) veya en cok kazandiran (revenue) urunleri siralar."""
    client = await get_db()
    where: OrderWhereInput | None = (
        {"category": {"equals": category}} if category else None
    )
    stats = await _product_stats(client, where)
    stats.sort(key=lambda r: r["units_sold" if metric == "units" else "revenue"], reverse=True)
    res = [
        {k: v for k, v in r.items() if k not in ("price_range", "order_count")}
        for r in stats[:limit]
    ]
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]


@mcp.tool
async def top_cities(
    product: str | None = None,
    category: CategoryName | None = None,
    payment_method: PaymentMethod | None = None,
    metric: Literal["units", "revenue"] = "units",
    limit: int = 10,
) -> list[TextContent]:
    """En cok urun satilan (units) veya en cok ciro getiren (revenue) sehirleri siralar."""
    client = await get_db()
    filters: list[OrderWhereInput] = []
    if product:
        resolved = await _resolve_product(client, product)
        if not resolved:
            return [TextContent(type="text", text=json.dumps({"found": False, "message": f"'{product}' adinda bir urun bulunamadi."}, ensure_ascii=False))]
        filters.append({"product": {"equals": resolved}})
    if category:
        filters.append({"category": {"equals": category}})
    if payment_method:
        filters.append({"paymentMethod": {"equals": payment_method}})

    where: OrderWhereInput | None = {"AND": filters} if filters else None

    city_groups = await client.order.group_by(
        ["customerCity"],
        where=where,
        count=True,
        sum={"quantity": True, "totalPrice": True},
    )

    cities = sorted(
        (
            {
                "city": g["customerCity"],
                "units_sold": g["_sum"]["quantity"],
                "revenue": _money(g["_sum"]["totalPrice"]),
                "order_count": g["_count"]["_all"],
            }
            for g in city_groups
        ),
        key=lambda c: c["revenue" if metric == "revenue" else "units_sold"],
        reverse=True,
    )[:limit]

    return [TextContent(type="text", text=json.dumps(cities, ensure_ascii=False))]


@mcp.tool
async def customer_demographics(
    product: str | None = None,
    category: CategoryName | None = None,
    payment_method: PaymentMethod | None = None,
) -> list[TextContent]:
    """Musterilerin yas gruplarini ve ortalama yasini analiz eder."""
    client = await get_db()
    filters: list[OrderWhereInput] = []
    if product:
        resolved = await _resolve_product(client, product)
        if not resolved:
            return [TextContent(type="text", text=json.dumps({"found": False, "message": f"'{product}' adinda bir urun bulunamadi."}, ensure_ascii=False))]
        filters.append({"product": {"equals": resolved}})
    if category:
        filters.append({"category": {"equals": category}})
    if payment_method:
        filters.append({"paymentMethod": {"equals": payment_method}})

    where: OrderWhereInput | None = {"AND": filters} if filters else None

    orders = await client.order.find_many(where=where)

    if not orders:
        return [TextContent(type="text", text=json.dumps({"found": False, "message": "Veri bulunamadi."}, ensure_ascii=False))]

    ages = [o.customerAge for o in orders]
    avg_age = round(sum(ages) / len(ages), 1)

    brackets = {"<25": 0, "25-34": 0, "35-49": 0, "50+": 0}
    for a in ages:
        if a < 25:
            brackets["<25"] += 1
        elif a <= 34:
            brackets["25-34"] += 1
        elif a <= 49:
            brackets["35-49"] += 1
        else:
            brackets["50+"] += 1

    res = {
        "found": True,
        "total_buyers": len(orders),
        "avg_age": avg_age,
        "min_age": min(ages),
        "max_age": max(ages),
        "age_brackets": brackets,
    }
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]


@mcp.tool
async def sales_trends(
    product: str | None = None,
    category: CategoryName | None = None,
    payment_method: PaymentMethod | None = None,
) -> list[TextContent]:
    """Zaman bazli (yillik/aylik) satis trendlerini ve en cok siparis alinan donemleri analiz eder."""
    client = await get_db()
    filters: list[OrderWhereInput] = []
    if product:
        resolved = await _resolve_product(client, product)
        if not resolved:
            return [TextContent(type="text", text=json.dumps({"found": False, "message": f"'{product}' adinda bir urun bulunamadi."}, ensure_ascii=False))]
        filters.append({"product": {"equals": resolved}})
    if category:
        filters.append({"category": {"equals": category}})
    if payment_method:
        filters.append({"paymentMethod": {"equals": payment_method}})

    where: OrderWhereInput | None = {"AND": filters} if filters else None

    orders = await client.order.find_many(where=where)

    if not orders:
        return [TextContent(type="text", text=json.dumps({"found": False, "message": "Veri bulunamadi."}, ensure_ascii=False))]

    by_year: dict[str, int] = {}
    by_month: dict[str, int] = {}

    for o in orders:
        parts = o.purchaseDate.split("-")
        if len(parts) >= 1:
            y = parts[0]
            by_year[y] = by_year.get(y, 0) + o.quantity
        if len(parts) >= 2:
            ym = f"{parts[0]}-{parts[1]}"
            by_month[ym] = by_month.get(ym, 0) + o.quantity

    top_months = sorted(
        [{"period": k, "units": v} for k, v in by_month.items()],
        key=lambda x: x["units"],
        reverse=True,
    )[:5]

    res = {
        "found": True,
        "total_orders": len(orders),
        "sales_by_year": by_year,
        "top_sales_months": top_months,
    }
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]


@mcp.tool
async def get_customer_history(email: str, limit: int = 20) -> list[TextContent]:
    """Musterinin e-postasina gore siparis gecmisini ve ozetini dokumler."""
    client = await get_db()
    orders = await client.order.find_many(
        where={"customerEmail": email},
        order={"purchaseDate": "desc"},
        take=limit,
    )
    if not orders:
        return [TextContent(type="text", text=json.dumps({"found": False, "message": f"{email} adresine ait siparis bulunamadi."}, ensure_ascii=False))]

    first = orders[0]
    res = {
        "found": True,
        "customer_email": first.customerEmail,
        "customer_city": first.customerCity,
        "customer_age": first.customerAge,
        "order_count": len(orders),
        "total_spent": _money(sum(o.totalPrice for o in orders)),
        "categories_bought": sorted({o.category for o in orders}),
        "orders": [
            {
                "order_id": o.orderId,
                "date": o.purchaseDate,
                "product": o.product,
                "category": o.category,
                "quantity": o.quantity,
                "unit_price": _money(o.unitPrice),
                "total_price": _money(o.totalPrice),
                "payment_method": o.paymentMethod,
            }
            for o in orders
        ],
    }
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]


@mcp.tool
async def get_order(order_id: str) -> list[TextContent]:
    """Siparis ID'sine gore siparis detaylarini dondurur."""
    client = await get_db()
    o = await client.order.find_unique(where={"orderId": order_id})
    if o is None:
        return [TextContent(type="text", text=json.dumps({"found": False, "message": f"{order_id} numarali siparis bulunamadi."}, ensure_ascii=False))]
    res = {
        "found": True,
        "order_id": o.orderId,
        "date": o.purchaseDate,
        "customer_email": o.customerEmail,
        "customer_city": o.customerCity,
        "product": o.product,
        "category": o.category,
        "quantity": o.quantity,
        "unit_price": _money(o.unitPrice),
        "total_price": _money(o.totalPrice),
        "payment_method": o.paymentMethod,
    }
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]


@mcp.tool
async def sales_overview() -> list[TextContent]:
    """Magazanin genel siparis, ciro ve satis istatistiklerini raporlar."""
    client = await get_db()

    order_count = await client.order.count()

    category_groups = await client.order.group_by(
        ["category"], count=True, sum={"totalPrice": True, "quantity": True}
    )
    revenue = sum(g["_sum"]["totalPrice"] for g in category_groups)
    top_categories = sorted(
        (
            {
                "category": g["category"],
                "revenue": _money(g["_sum"]["totalPrice"]),
                "units": g["_sum"]["quantity"],
            }
            for g in category_groups
        ),
        key=lambda c: c["revenue"],
        reverse=True,
    )[:5]

    customer_count = len(await client.order.group_by(["customerEmail"]))
    product_count = len(await client.order.group_by(["product"]))

    first = await client.order.find_first(order={"purchaseDate": "asc"})
    last = await client.order.find_first(order={"purchaseDate": "desc"})

    payment_groups = await client.order.group_by(["paymentMethod"], count=True)
    payments = sorted(
        (
            {"method": g["paymentMethod"], "count": g["_count"]["_all"]}
            for g in payment_groups
        ),
        key=lambda p: p["count"],
        reverse=True,
    )

    res = {
        "order_count": order_count,
        "customer_count": customer_count,
        "product_count": product_count,
        "total_revenue": _money(revenue),
        "avg_order_value": _money(revenue / order_count) if order_count else 0.0,
        "date_range": [
            first.purchaseDate if first else None,
            last.purchaseDate if last else None,
        ],
        "top_categories": top_categories,
        "payment_methods": payments,
    }
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stdio":
        mcp.run(transport="stdio")
    else:
        print("MCP Server HTTP (SSE) modunda baslatiliyor: http://0.0.0.0:8000/sse")
        mcp.run(transport="sse", host="0.0.0.0", port=8000)
