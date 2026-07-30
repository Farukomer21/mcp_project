# Satış Danışmanı Agent (Gemini + FastMCP + Prisma)

```
agent.py  ──stdio──>  server.py (FastMCP)  ──Prisma──>  data.db (SQLite)
  Gemini                 8 tool                  synthetic_ecommerce_dataset
```

Agent, MCP sunucusunu alt süreç olarak başlatır. Tool şemaları doğrudan Gemini'ye
verilir; tool çağrılarını google-genai SDK'sının otomatik fonksiyon çağırma (AFC)
mekanizması yürütür — elle bir tool döngüsü yazmaya gerek yok.

## Kurulum

```bash
uv sync
uv run prisma generate     # şema değiştiğinde tekrar çalıştır
```

`.env` dosyasına Gemini anahtarını ekle:

```
DATABASE_URL="file:../data.db"
GEMINI_API_KEY="..."
GEMINI_MODEL="gemini-2.5-flash"   # opsiyonel
```

## Çalıştırma

```bash
uv run agent.py            # sohbet arayüzü
uv run server.py           # sadece MCP sunucusu (Claude Desktop vb. için)
```

## Tool'lar (`server.py`)

| Tool | Ne yapar |
|---|---|
| `list_categories` | 20 kategori, ürün sayısı, ortalama fiyat |
| `list_products` | Kategoriye göre ürünler + fiyat aralığı, satış adedi |
| `search_products` | İsim/kategori/bütçe filtresiyle arama |
| `get_product_details` | Tek ürün: fiyat, ciro, popüler şehirler, ödeme yöntemleri |
| `top_products` | En çok satanlar (adet veya ciro bazlı) |
| `get_customer_history` | E-postaya göre sipariş geçmişi + özet |
| `get_order` | Sipariş no ile tek sipariş |
| `sales_overview` | Genel mağaza istatistikleri |

Hepsi salt-okunur. Yeni tool eklemek için `server.py` içine `@mcp.tool` ile bir
async fonksiyon yaz — docstring'i Gemini'nin gördüğü açıklamadır, o yüzden
tool'u ne zaman kullanacağını docstring'de anlat.

## SDK notları (google-genai 2.15.0)

Canlı bir MCP `ClientSession`'ı Gemini'ye tool olarak vermek iki yerde patlıyor.
`agent.py` ikisini de baypas ediyor:

1. **`config` dict olarak veriliyor, `GenerateContentConfig` objesi olarak değil.**
   SDK, config objesi aldığında MCP session'ını ayıklamadan *önce*
   `config.model_copy(deep=True)` yapıyor; canlı session deepcopy edilemediği için
   `TypeError: cannot pickle '_asyncio.Future'` alıyorsun. Dict dalında bu kopyalama yok.
   Aynı sebeple `client.aio.chats` kullanılamıyor (config'i her zaman objeye çevirir) —
   bu yüzden sohbet geçmişi elle yönetiliyor.
2. **`SanitizedClientSession` tool şemalarını temizliyor.** FastMCP şemaya
   `"additionalProperties": false` koyuyor; SDK'nın şema dönüştürücüsü bu alanı her
   zaman iç içe bir şema sanıp `False.items()` çağırıyor →
   `AttributeError: 'bool' object has no attribute 'items'`. Wrapper değil **alt sınıf**
   kullanmak şart, çünkü SDK session'ı `isinstance` ile tespit ediyor.

SDK sürümünü yükseltirken bu ikisinin hâlâ gerekli olup olmadığını kontrol et.

## Veri notları

- Tek tablo, 10.000 sipariş satırı (2024-03-20 → 2025-03-20), 20 kategori, 80 ürün.
- Ayrı ürün/müşteri tablosu yok: katalog ve müşteri profili sipariş satırlarından
  türetiliyor. Bu yüzden "fiyat" sabit değil, geçmiş siparişlerin **ortalaması**.
- Stok bilgisi yok — agent stok sorusuna cevap veremez.
- Sentetik veri: aynı e-posta farklı isimlerle görünebilir.
