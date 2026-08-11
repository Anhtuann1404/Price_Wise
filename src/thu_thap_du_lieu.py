"""
PriceWise v4.0 - Thu thập & Làm sạch Dữ liệu TMĐT từ Tiki & Shopee (Multi-Platform).

🚀 Cập nhật v4.0:
  ✅ Tích hợp Shopee API (demo vài trăm sản phẩm)
  ✅ Thêm cột 'nen_tang' phân biệt Tiki vs Shopee
  ✅ Error handling chặt chẽ cho Shopee (lỗi 403, timeout, v.v.)
  ✅ Thêm Mock Data: Tự tạo data Shopee giả lập nếu bị API chặn để test bảng.
"""

import json
import pandas as pd
import numpy as np
import requests
import time
import logging
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from collections import Counter
from datetime import datetime


# ============================================================================
# LOGGING & CONFIGURATION
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# Tiki - Category mapping
NGANH_HANG_MAPPING = {
    "8322": "Sách tiếng Việt",
    "316": "Sách ngoại văn",
    "1084": "Truyện tranh/Manga",
    "67998": "Sách thiếu nhi",
    "871": "Tô màu - Luyện chữ",
    "1789": "Điện thoại - Máy tính bảng",
    "1815": "Thiết bị số - Phụ kiện",
    "915": "Thời trang nam",
    "931": "Thời trang nữ",
    "1520": "Làm đẹp - Sức khỏe",
    "1883": "Nhà cửa - Đời sống",
    "4384": "Bách hóa online",
}

NGANH_HANG_THU_TAP_TIKI = [
    ("8322", "Sách tiếng Việt", 3),
    ("1084", "Truyện tranh/Manga", 2),
    ("1789", "Điện thoại - Máy tính bảng", 2),
]

# Shopee - Category (demo)
SHOPEE_SEARCH_KEYWORDS = [
    ("sách", 2),
    ("điện thoại", 2),
    ("thời trang nam", 2),
]

# API Endpoints
TIKI_API_BASE = "https://tiki.vn/api/personalish/v1/blocks/listings"
SHOPEE_API_BASE = "https://shopee.vn/api/v4/search/search_items"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def extract_quantity_sold(value) -> int:
    try:
        if isinstance(value, dict):
            return int(value.get('value', 0))
        if isinstance(value, (int, float)):
            return int(max(value, 0))
        if isinstance(value, str):
            match = re.search(r'\d+', value)
            return int(match.group()) if match else 0
        return 0
    except Exception as e:
        logger.warning(f"⚠ Lỗi parse quantity_sold: {value}")
        return 0


def map_nganh_hang_tiki(category_path: str) -> str:
    """Map chuỗi path mã ngành Tiki → Tên Việt (Ưu tiên danh mục con)."""
    if not category_path or pd.isna(category_path):
        return "Chưa phân loại"
    ids = str(category_path).split('/')
    for cat_id in reversed(ids):
        if cat_id in NGANH_HANG_MAPPING:
            return NGANH_HANG_MAPPING[cat_id]
    return f"Ngành {ids[-1]}"


# ============================================================================
# CLASS: ThuThapTiki
# ============================================================================

class ThuThapTiki:
    def __init__(self, max_retries: int = 3, timeout: int = 10):
        self.du_lieu_tho = []
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.max_retries = max_retries
        self.timeout = timeout

    def kiem_tra_api_truoc_khi_chay(self) -> bool:
        logger.info("🏥 HEALTH-CHECK TIKI: Kiểm tra API Tiki trước khi chạy...")
        try:
            test_url = f"{TIKI_API_BASE}?limit=10&category=8322&page=1"
            response = requests.get(test_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json().get('data', [])
            if not data:
                logger.error("❌ API Tiki trả về data trống")
                return False
            logger.info(f"✅ Health-check Tiki thành công! ({len(data)} items)")
            return True
        except Exception as e:
            logger.error(f"❌ Health-check Tiki fail: {type(e).__name__}")
            return False

    def goi_api_tiki_multi(self, nganh_hang_list: List[Tuple[str, str, int]] = None, delay: float = 1.5) -> bool:
        if not self.kiem_tra_api_truoc_khi_chay():
            logger.error("🛑 Dừng Tiki do health-check fail")
            return False

        if nganh_hang_list is None:
            nganh_hang_list = NGANH_HANG_THU_TAP_TIKI

        tong_sp = 0
        logger.info(f"🔄 Thu thập Tiki từ {len(nganh_hang_list)} ngành hàng...")

        for ma_nganh, ten_nganh, so_trang in nganh_hang_list:
            logger.info(f"   📥 {ten_nganh} (Mã: {ma_nganh}) | {so_trang} trang")
            sp_nganh = 0

            for page in range(1, so_trang + 1):
                try:
                    url = f"{TIKI_API_BASE}?limit=40&category={ma_nganh}&page={page}"
                    response = requests.get(url, headers=self.headers, timeout=self.timeout)
                    response.raise_for_status()
                    data = response.json().get('data', [])

                    if data:
                        self.du_lieu_tho.extend(data)
                        sp_nganh += len(data)
                        tong_sp += len(data)
                        logger.info(f"      ✓ Trang {page}: {len(data)} sp | Tổng: {tong_sp}")

                    if page < so_trang:
                        time.sleep(delay)
                except requests.exceptions.Timeout:
                    logger.warning(f"      ⏱️  Timeout trang {page}, thử lại...")
                    time.sleep(2)
                except Exception as e:
                    logger.warning(f"      ⚠ Trang {page}: {type(e).__name__}")

            logger.info(f"   → {ten_nganh}: {sp_nganh} sp")

        # Loại trùng
        du_lieu_unique = []
        ma_sp_seen = set()
        for item in self.du_lieu_tho:
            ma_sp = item.get('id')
            if ma_sp not in ma_sp_seen:
                ma_sp_seen.add(ma_sp)
                du_lieu_unique.append(item)
        self.du_lieu_tho = du_lieu_unique

        logger.info(f"\n✅ TIKI HOÀN THÀNH: {len(self.du_lieu_tho)} sản phẩm (loại trùng)")
        return len(self.du_lieu_tho) > 0


# ============================================================================
# CLASS: ThuThapShopee (Cập nhật: Thêm Mock Data để test multi-platform)
# ============================================================================

class ThuThapShopee:
    def __init__(self, max_retries: int = 3, timeout: int = 15):
        self.du_lieu_tho = []
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://shopee.vn/'
        }
        self.max_retries = max_retries
        self.timeout = timeout
        self.bi_chan = False

    def tao_du_lieu_gia_lap(self):
        """Tạo dữ liệu Shopee mẫu để test logic gộp khi API thật bị chặn."""
        logger.info("   👉 Đang tạo dữ liệu Shopee giả lập để test cấu trúc bảng...")
        self.du_lieu_tho.extend([
            {
                "itemid": "SP001",
                "shopid": "SHOP99",
                "name": "[Shopee Test] Sách Đắc Nhân Tâm - Hàng Chính Hãng",
                "price": 8500000000, # API Shopee nhân giá gốc với 100,000
                "item_rating": {"rating_average": 4.9},
                "sold": 1250
            },
            {
                "itemid": "SP002",
                "shopid": "SHOP99",
                "name": "[Shopee Test] Điện thoại iPhone 15 Pro Max 256GB",
                "price": 2950000000000,
                "item_rating": {"rating_average": 4.8},
                "sold": 340
            },
            {
                "itemid": "SP003",
                "shopid": "SHOP99",
                "name": "[Shopee Test] Áo thun nam cotton form rộng",
                "price": 15000000000,
                "item_rating": {"rating_average": 4.5},
                "sold": 5000
            }
        ])

    def kiem_tra_api_truoc_khi_chay(self) -> bool:
        logger.info("🏥 HEALTH-CHECK SHOPEE: Kiểm tra API Shopee...")
        try:
            response = requests.get(
                SHOPEE_API_BASE,
                params={'keyword': 'sách', 'limit': 10, 'offset': 0},
                headers=self.headers,
                timeout=self.timeout
            )
            if response.status_code == 403:
                logger.error("❌ Shopee chặn bot (403 Forbidden)")
                self.bi_chan = True
                return False
            response.raise_for_status()
            data = response.json().get('items', [])
            if not data:
                return False
            return True
        except Exception:
            self.bi_chan = True
            return False

    def goi_api_shopee(self, keyword_list: List[Tuple[str, int]] = None, delay: float = 3.0) -> bool:
        if not self.kiem_tra_api_truoc_khi_chay() or self.bi_chan:
            logger.warning("⚠️ API Shopee không khả dụng. Kích hoạt chế độ Mock Data.")
            self.tao_du_lieu_gia_lap()
            return True

        if keyword_list is None:
            keyword_list = SHOPEE_SEARCH_KEYWORDS

        tong_sp = 0
        for keyword, so_page in keyword_list:
            for page in range(so_page):
                if self.bi_chan: break
                try:
                    response = requests.get(
                        SHOPEE_API_BASE,
                        params={'keyword': keyword, 'limit': 50, 'offset': page * 50},
                        headers=self.headers,
                        timeout=self.timeout
                    )
                    if response.status_code == 403:
                        self.bi_chan = True
                        break
                    response.raise_for_status()
                    data = response.json().get('items', [])
                    if data:
                        self.du_lieu_tho.extend(data)
                    time.sleep(delay)
                except Exception:
                    continue

        # Nếu đã chạy mà vẫn không có data (do lỗi), thì bơm data giả lập vào
        if not self.du_lieu_tho:
            self.tao_du_lieu_gia_lap()

        # Loại trùng lặp
        du_lieu_unique = []
        ma_sp_seen = set()
        for item in self.du_lieu_tho:
            ma_sp = str(item.get('itemid', item.get('id')))
            if ma_sp not in ma_sp_seen:
                ma_sp_seen.add(ma_sp)
                du_lieu_unique.append(item)
        self.du_lieu_tho = du_lieu_unique

        logger.info(f"\n✅ SHOPEE HOÀN THÀNH: {len(self.du_lieu_tho)} sản phẩm")
        return len(self.du_lieu_tho) > 0


# ============================================================================
# CLASS: LamSachDuLieu
# ============================================================================

class LamSachDuLieu:
    def __init__(self, du_lieu_tiki: List[Dict], du_lieu_shopee: List[Dict]):
        self.du_lieu_tiki = du_lieu_tiki
        self.du_lieu_shopee = du_lieu_shopee
        self.df = None
        self.nhop = pd.DataFrame()
        self.log = logger

    def chuyen_doi_shopee(self, item: Dict) -> Dict:
        return {
            'id': str(item.get('itemid', '')),
            'name': item.get('name', ''),
            'price': float(item.get('price', 0)) / 100000 if item.get('price') else 0,
            'rating_average': float(item.get('item_rating', {}).get('rating_average', 0)) if item.get('item_rating') else 0,
            'quantity_sold': item.get('sold', 0),
            'url': f"https://shopee.vn/-{item.get('name', '')}-i.{item.get('shopid', '')}.{item.get('itemid', '')}",
        }

    def gop_du_lieu(self):
        self.log.info("📊 Gộp dữ liệu Tiki + Shopee...")

        du_lieu_tiki_clean = []
        for item in self.du_lieu_tiki:
            du_lieu_tiki_clean.append({
                'id': str(item.get('id', '')),
                'name': item.get('name', ''),
                'price': float(item.get('price', 0)),
                'rating_average': float(item.get('rating_average', 0)),
                'quantity_sold': extract_quantity_sold(item.get('quantity_sold')),
                'primary_category_path': item.get('primary_category_path', ''),
                'url': f"https://tiki.vn/{item.get('url_path', '')}",
            })

        du_lieu_shopee_clean = []
        for item in self.du_lieu_shopee:
            du_lieu_shopee_clean.append(self.chuyen_doi_shopee(item))

        df_tiki = pd.DataFrame(du_lieu_tiki_clean)
        df_shopee = pd.DataFrame(du_lieu_shopee_clean)

        df_tiki['nen_tang'] = 'Tiki'
        df_shopee['nen_tang'] = 'Shopee'

        if len(df_tiki) > 0:
            df_tiki['nganh_hang'] = df_tiki['primary_category_path'].apply(map_nganh_hang_tiki)
        else:
            df_tiki['nganh_hang'] = ''

        df_shopee['nganh_hang'] = 'Khác (Shopee)'

        cols_common = ['id', 'name', 'price', 'rating_average', 'quantity_sold', 'url', 'nen_tang', 'nganh_hang']
        df_tiki_select = df_tiki[cols_common] if len(df_tiki) > 0 else pd.DataFrame(columns=cols_common)
        df_shopee_select = df_shopee[cols_common] if len(df_shopee) > 0 else pd.DataFrame(columns=cols_common)

        self.df = pd.concat([df_tiki_select, df_shopee_select], ignore_index=True)
        self.log.info(f"   ✓ Gộp xong: {len(self.df)} sản phẩm (Tiki: {len(df_tiki)}, Shopee: {len(df_shopee)})")

    def anh_xa_cot(self) -> pd.DataFrame:
        if self.df is None:
            self.gop_du_lieu()

        self.log.info("📍 Bước 1: Chuẩn hóa cột...")
        self.df.rename(columns={
            'id': 'ma_san_pham',
            'name': 'ten_san_pham',
            'price': 'gia',
            'rating_average': 'danh_gia',
            'quantity_sold': 'luot_ban',
        }, inplace=True)

        if 'gia_goc' not in self.df.columns:
            self.df['gia_goc'] = self.df['gia']
        if 'ty_le_giam' not in self.df.columns:
            self.df['ty_le_giam'] = 0
        if 'shop' not in self.df.columns:
            self.df['shop'] = self.df['nen_tang']

        self.log.info(f"   ✓ Chuẩn hóa: {len(self.df)} dòng, {len(self.df.columns)} cột")
        return self.df

    def xu_ly_thieu_trung(self):
        if self.df is None:
            self.anh_xa_cot()

        self.log.info("📍 Bước 2: Xử lý NULL & trùng lặp...")
        so_dong_truoc = len(self.df)
        self.df = self.df.dropna(subset=['ma_san_pham', 'ten_san_pham', 'gia'], how='any')

        self.df['danh_gia'] = self.df['danh_gia'].fillna(0)
        self.df['luot_ban'] = self.df['luot_ban'].fillna(0).astype(int)
        self.df['ty_le_giam'] = self.df['ty_le_giam'].fillna(0)

        self.df = self.df.drop_duplicates(subset=['ma_san_pham'], keep='first')
        self.log.info(f"   ✓ Sau xử lý: {len(self.df)} dòng")

    def ep_kieu_du_lieu(self):
        if self.df is None:
            self.xu_ly_thieu_trung()

        self.log.info("📍 Bước 3: Ép kiểu dữ liệu...")
        self.df['gia'] = pd.to_numeric(self.df['gia'], errors='coerce').fillna(0)
        self.df['danh_gia'] = self.df['danh_gia'].clip(0, 5).astype(float)
        self.df['ty_le_giam'] = self.df['ty_le_giam'].clip(0, 1).astype(float)
        self.df['luot_ban'] = self.df['luot_ban'].astype(int)

        self.df = self.df[self.df['gia'] > 0]
        self.log.info(f"   ✓ Ép kiểu: {len(self.df)} dòng hợp lệ")

    def xu_ly_ngoai_lai(self):
        if self.df is None:
            self.ep_kieu_du_lieu()

        self.log.info("📍 Bước 4: Phát hiện ngoại lai...")
        self.df['da_kiem_tra_gia_ao'] = False

        Q1 = self.df['gia'].quantile(0.25)
        Q3 = self.df['gia'].quantile(0.75)
        IQR = Q3 - Q1
        lower = Q1 - 1.5 * IQR
        upper = Q3 + 1.5 * IQR
        ngoai_lai_iqr = (self.df['gia'] < lower) | (self.df['gia'] > upper)

        mean_gia = self.df['gia'].mean()
        std_gia = self.df['gia'].std()
        z_score = np.abs((self.df['gia'] - mean_gia) / (std_gia + 1e-10))
        ngoai_lai_z = z_score > 3.0

        self.df.loc[ngoai_lai_iqr | ngoai_lai_z, 'da_kiem_tra_gia_ao'] = True
        self.nhop = self.df[self.df['da_kiem_tra_gia_ao'] == True].copy()
        self.log.info(f"   ✓ Phát hiện {self.df['da_kiem_tra_gia_ao'].sum()} ngoại lai")

    def lay_du_lieu_sach(self) -> pd.DataFrame:
        self.anh_xa_cot()
        self.xu_ly_thieu_trung()
        self.ep_kieu_du_lieu()
        self.xu_ly_ngoai_lai()

        self.log.info(f"\n{'='*70}")
        self.log.info(f"✅ DỮ LIỆU ĐÃ CHUẨN HÓA")
        self.log.info(f"{'='*70}")
        self.log.info(f"  📊 Tổng: {len(self.df):,}")
        self.log.info(f"  🏪 Nền tảng: {self.df['nen_tang'].value_counts().to_dict()}")
        self.log.info(f"{'='*70}\n")
        return self.df


# ============================================================================
# SCRIPT CHÍNH
# ============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("🚀 PRICEWISE v4.0 - THU THẬP TỪ TIKI & SHOPEE")
    print("=" * 70 + "\n")

    logger.info("🔷 BƯỚC 1: THU THẬP TIKI")
    bot_tiki = ThuThapTiki()
    success_tiki = bot_tiki.goi_api_tiki_multi()
    du_lieu_tiki = bot_tiki.du_lieu_tho if success_tiki else []

    logger.info("\n🔶 BƯỚC 2: THU THẬP SHOPEE")
    bot_shopee = ThuThapShopee()
    success_shopee = bot_shopee.goi_api_shopee()
    du_lieu_shopee = bot_shopee.du_lieu_tho if success_shopee else []

    logger.info("\n🧹 BƯỚC 3: LÀM SẠCH DỮ LIỆU MULTI-PLATFORM")
    lam_sach = LamSachDuLieu(du_lieu_tiki, du_lieu_shopee)
    df_sach = lam_sach.lay_du_lieu_sach()

    logger.info("\n💾 BƯỚC 4: XUẤT DỮ LIỆU")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    csv_file = f"dulieu_multi_v4_{timestamp}.csv"
    df_sach.to_csv(csv_file, index=False, encoding='utf-8-sig')
    logger.info(f"✓ CSV: {csv_file}")

    json_file = f"dulieu_multi_v4_{timestamp}.json"
    df_sach.to_json(json_file, orient='records', force_ascii=False, indent=2)
    logger.info(f"✓ JSON: {json_file}")

    logger.info("\n📋 Mẫu dữ liệu (Lấy 10 dòng cuối để thấy Shopee):")
    print(df_sach[['ma_san_pham', 'ten_san_pham', 'nen_tang', 'nganh_hang', 'gia', 'danh_gia']].tail(10).to_string())

    logger.info("\n✅ HOÀN THÀNH!")