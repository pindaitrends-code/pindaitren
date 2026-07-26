# save_to_firebase.py - VERSI FINAL DENGAN SMART DISCOVERY + SINYAL PRODUK
import os
import json
import hashlib
import re
from datetime import datetime
from apify_client import ApifyClient
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Load API Key dari .env
load_dotenv()
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")

if not APIFY_TOKEN:
    print("❌ APIFY_API_TOKEN tidak ditemukan di .env!")
    exit()

print("✅ APIFY_API_TOKEN ditemukan!")

# Inisialisasi Firebase
print("🔥 Inisialisasi Firebase...")
cred = credentials.Certificate("service-account.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
print("✅ Firebase connected!")

# ============================================
# 🔧 FUNGSI AMAN UNTUK AMBIL ANGKA
# ============================================
def safe_int(value, default=0):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = re.sub(r'[^\d]', '', value)
        if cleaned:
            return int(cleaned)
    return default

def safe_float(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r'[^\d.]', '', value.replace(',', '.'))
        if cleaned:
            try:
                return float(cleaned)
            except:
                pass
    return default

def safe_string(value, default=''):
    if value is None:
        return default
    return str(value)

# ============================================
# 🔗 GENERATE LINK AFILIASI
# ============================================
def generate_affiliate_link(platform: str, product_url: str, product_id: str) -> str:
    # ⚠️ GANTI DENGAN ID AFILIASI ASLI ANDA!
    AFFILIATE_IDS = {
        "shopee": "12345678",
        "tokopedia": "aff_12345",
        "lazada": "12345678",
        "tiktok": "12345678"
    }
    
    platform_lower = platform.lower()
    aff_id = AFFILIATE_IDS.get(platform_lower, "")
    
    if not aff_id or not product_id:
        return product_url
    
    if "shopee" in platform_lower:
        return f"https://shope.ee/{product_id}?affiliate_id={aff_id}"
    elif "tokopedia" in platform_lower:
        return f"https://tokopedia.link/{product_id}?aff_id={aff_id}"
    elif "lazada" in platform_lower:
        return f"https://lazada.co.id/{product_id}?affiliate_id={aff_id}"
    elif "tiktok" in platform_lower:
        return f"https://vt.tokopedia.com/t/{product_id}?affiliate_id={aff_id}"
    else:
        return product_url

# ============================================
# 🖼️ EKSTRAK GAMBAR
# ============================================
def extract_image_url(item):
    possible_fields = ['image_url', 'main_image', 'image', 'thumbnail', 'picture', 'images', 'cover', 'photo', 'img']
    
    for field in possible_fields:
        val = item.get(field, '')
        if val:
            if isinstance(val, list) and len(val) > 0:
                first = val[0]
                if isinstance(first, str) and first.startswith(('http://', 'https://')):
                    return first
            elif isinstance(val, str) and val.startswith(('http://', 'https://')):
                return val
    
    url = item.get('url', '')
    if url:
        match = re.search(r'/pdp/([^/?]+)', url)
        if match:
            product_id = match.group(1).split('/')[0]
            return f"https://images.tokopedia.net/img/cache/700/product-1/{product_id}.jpg"
    
    return None

# ============================================
# 🧠 EKSTRAK SINYAL PRODUK (Tanpa Kategori Kaku)
# ============================================
def extract_product_signals(item):
    """Ekstrak sinyal kualitas produk tanpa kategorisasi manual"""
    signals = {
        'is_discount': False,
        'is_high_rating': False,
        'is_best_seller': False,
        'is_trending': False,
        'signal_score': 0
    }
    
    # 1️⃣ Sinyal Diskon
    discount = safe_int(item.get('discount', 0))
    original_price = safe_int(item.get('original_price', 0))
    price = safe_int(item.get('price', 0))
    
    if discount >= 30 or (original_price > 0 and price > 0 and (original_price - price) / original_price >= 0.3):
        signals['is_discount'] = True
        signals['signal_score'] += 35
    
    # 2️⃣ Sinyal Rating
    rating = safe_float(item.get('rating', 0))
    if rating >= 4.5:
        signals['is_high_rating'] = True
        signals['signal_score'] += 30
    
    # 3️⃣ Sinyal Penjualan
    sold = safe_int(item.get('sold_count', 0))
    if sold >= 5000:
        signals['is_best_seller'] = True
        signals['signal_score'] += 25
    elif sold >= 1000:
        signals['is_best_seller'] = True
        signals['signal_score'] += 15
    
    # 4️⃣ Sinyal Trending (dari review count)
    reviews = safe_int(item.get('review_count', 0))
    if reviews >= 500:
        signals['is_trending'] = True
        signals['signal_score'] += 10
    
    # 5️⃣ Bonus: Produk dengan diskon + rating tinggi
    if signals['is_discount'] and signals['is_high_rating']:
        signals['signal_score'] += 20
    
    return signals

# ============================================
# 🚀 SMART DISCOVERY MODE - All-in produk terbaik!
# ============================================
client = ApifyClient(APIFY_TOKEN)

print("🚀 Scraping TikTok Shop - SMART DISCOVERY MODE...")
print("🎯 Target: Produk diskon terbaik, rating tinggi, penjualan terbanyak")

run_input = {
    # 🔥 Keyword dinamis untuk menangkap produk terbaik
    "searchKeywords": [
        "diskon", "flash sale", "viral", "best seller", 
        "promo", "terlaris", "trending", "hot item", "rekomendasi"
    ],
    "maxResults": 150,
    "minRating": 4.0,
    "minUnitsSold": 100,
}

run = client.actor("kulqiz/tiktok-shop-scraper").call(run_input=run_input)
dataset_id = run.default_dataset_id
print(f"✅ Dataset ID: {dataset_id}")

items = list(client.dataset(dataset_id).iterate_items())
print(f"📊 {len(items)} produk ditemukan")

# ============================================
# 💾 SIMPAN KE FIRESTORE
# ============================================
print("💾 Menyimpan ke Firestore...")
saved = 0
skipped = 0

for item in items:
    try:
        url = safe_string(item.get('url', ''))
        product_id = url.split('/pdp/')[-1].split('/')[0] if '/pdp/' in url else hashlib.md5(url.encode()).hexdigest()[:12]
        
        # 🔥 AMBIL HARGA
        price = safe_int(item.get('sale_price', 0))
        if price == 0:
            price = safe_int(item.get('price', 0))
        if price == 0:
            price = safe_int(item.get('current_price', 0))
        if price == 0:
            price = safe_int(item.get('promo_price', 0))
        
        original_price = safe_int(item.get('original_price', 0))
        if original_price == 0 and price > 0:
            discount = safe_int(item.get('discount', 0))
            if discount > 0:
                original_price = int(price / (1 - discount/100))
        
        discount = safe_int(item.get('discount', 0))
        rating = safe_float(item.get('rating', 0))
        if rating == 0:
            rating = safe_float(item.get('star', 0))
        
        review_count = safe_int(item.get('review_count', 0))
        if review_count == 0:
            review_count = safe_int(item.get('reviews', 0))
        
        sold_count = safe_int(item.get('sold_count', 0))
        if sold_count == 0:
            sold_count = safe_int(item.get('sold', 0))
        
        shop_name = safe_string(item.get('shop_name', ''))
        if not shop_name:
            shop_name = safe_string(item.get('seller_name', ''))
        
        shop_rating = safe_float(item.get('shop_rating', 0))
        image_url = extract_image_url(item)
        platform = safe_string(item.get('platform', 'tiktok'))
        affiliate_link = generate_affiliate_link(platform, url, product_id)
        
        # 🔥 FILTER: Skip produk dengan harga anomali
        if 0 < price < 1000:
            skipped += 1
            continue
        
        # 🔥 Ambil sinyal produk
        signals = extract_product_signals(item)
        
        product_data = {
            "id": product_id,
            "judul": safe_string(item.get('title', 'No title'))[:200],
            "harga": price,
            "harga_asli": original_price,
            "diskon": discount,
            "peringkat": rating,
            "jumlah_ulasan": review_count,
            "jumlah_terjual": sold_count,
            "nama_toko": shop_name,
            "rating_toko": shop_rating,
            "url": url,
            "link_afiliasi": affiliate_link,
            "platform": platform,
            "gambar": image_url,
            "smart_score": signals['signal_score'],
            "is_discount": signals['is_discount'],
            "is_high_rating": signals['is_high_rating'],
            "is_best_seller": signals['is_best_seller'],
            "is_trending": signals['is_trending'],
            "deskripsi": safe_string(item.get('description', ''))[:500],
            "dikerok_di": datetime.now().isoformat()
        }
        
        db.collection('products').document(product_id).set(product_data)
        saved += 1
        
        if saved <= 5 or saved % 10 == 0:
            print(f"  ✅ {saved}. {product_data['judul'][:40]}...")
            print(f"     💰 Rp {price:,} | ⭐ {rating} | 🖼️ {'✅' if image_url else '❌'}")
            print(f"     🛒 {sold_count:,} terjual | 🏪 {shop_name[:20]}")
            print(f"     🏷️ Diskon: {discount}% | Skor: {signals['signal_score']}")
            print()
            
    except Exception as e:
        print(f"⚠️ Error: {e}")
        continue

print(f"\n✅ {saved} produk berhasil disimpan ke Firebase!")
print(f"⏭️ {skipped} produk dilewati (harga anomali/rendah)")
print("📊 Data lengkap: harga, gambar, rating, terjual, link afiliasi!")

# ============================================
# 📊 STATISTIK
# ============================================
print("\n📊 STATISTIK DATA:")
print(f"   Total produk: {saved}")

prices = [item.get('harga', 0) for item in items if item.get('harga', 0) > 1000]
if prices:
    avg_price = sum(prices) / len(prices)
    print(f"   Harga rata-rata: Rp {avg_price:,.0f}")

ratings = [item.get('rating', 0) for item in items if item.get('rating', 0) > 0]
if ratings:
    avg_rating = sum(ratings) / len(ratings)
    print(f"   Rating rata-rata: {avg_rating:.1f}")

discounts = [item.get('diskon', 0) for item in items if item.get('diskon', 0) > 0]
if discounts:
    avg_discount = sum(discounts) / len(discounts)
    print(f"   Diskon rata-rata: {avg_discount:.0f}%")

print("✅ Selesai!")