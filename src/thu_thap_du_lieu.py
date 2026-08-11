"""
PriceWise v4.3 - Thu thập & Làm sạch Dữ liệu TMĐT (Tiki + Kaggle Dataset).
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

# ============================================================================
# CONSTANTS: TIKI 6 NGÀNH
# ============================================================================

NGANH_HANG_MAPPING = {
    "8322": "Sách tiếng Việt", "316": "Sách ngoại văn", "1084": "Truyện tranh/Manga",
    "67998": "Sách thiếu nhi", "871": "Tô màu - Luyện chữ", "915": "Thời trang nam",
    "931": "Thời trang nữ", "11": "Áo nam", "12": "Quần nam", "13": "Giày nam",
    "14": "Áo nữ", "15": "Quần nữ", "16": "Giày nữ", "17": "Phụ kiện thời trang",
    "1789": "Điện thoại - Máy tính bảng", "1815": "Thiết bị số - Phụ kiện",
    "1": "Điện thoại", "2": "Tablet", "3": "Laptop", "4": "Tai nghe",
    "5": "Phụ kiện điện thoại", "1520": "Làm đẹp - Sức khỏe", "385": "Mỹ phẩm",
    "664": "Chăm sóc da", "1754": "Máy massage", "853": "Vitamin & Thực phẩm bổ sung",
    "1883": "Nhà cửa - Đời sống", "4384": "Bách hóa online",
}

NGANH_HANG_THU_TAP_TIKI = [
    ("8322", "Sách tiếng Việt", 15),
    ("316", "Sách ngoại văn", 15),
    ("1084", "Truyện tranh/Manga", 15),
    ("11", "Áo nam", 15),
    ("1", "Điện thoại", 15),
    ("385", "Mỹ phẩm", 15),
]

TIKI_API_BASE = "https://tiki.vn/api/personalish/v1/blocks/listings"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def extract_quantity_sold(value) -> int:
    try:
        if isinstance(value, dict): return int(value.get('value', 0))
        if isinstance(value, (int, float)): return int(max(value, 0))
        if isinstance(value, str):
            match = re.search(r'\d+', value)
            return int(match.group()) if match else 0
        return 0
    except:
        return 0

def map_nganh_hang_tiki(category_path: str) -> str:
    if not category_path or pd.isna(category_path): return "Chưa phân loại"
    ids = str(category_path).split('/')
    for cat_id in reversed(ids):
        if cat_id in NGANH_HANG_MAPPING: return NGANH_HANG_MAPPING[cat_id]
    return f"Ngành {ids[-1] if ids else 'Unknown'}"

# ============================================================================
# CLASS: ThuThapTiki
# ============================================================================

class ThuThapTiki:
    def __init__(self, timeout: int = 10):
        self.du_lieu_tho = []
        self.headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        self.timeout = timeout

    def goi_api_tiki_multi(self) -> bool:
        tong_sp = 0
        logger.info(f"🔄 Thu thập Tiki từ 6 ngành hàng...")

        for ma_nganh, ten_nganh, so_trang in NGANH_HANG_THU_TAP_TIKI:
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
                    time.sleep(1.0)
                except Exception:
                    pass
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
        logger.info(f"\n✅ TIKI HOÀN THÀNH: {len(self.du_lieu_tho)} sản phẩm")
        return len(self.du_lieu_tho) > 0

# ============================================================================
# CLASS: DocKaggles
# ============================================================================

class DocKaggles:
    def __init__(self, csv_path: str):
        self.du_lieu_tho = []
        self.csv_path = csv_path

    def doc_tu_csv(self) -> bool:
        logger.info("📂 KAGGLE: Đọc dữ liệu từ CSV...")

        if not self.csv_path or not Path(self.csv_path).exists():
            return False

        try:
            df = pd.read_csv(self.csv_path, encoding='utf-8', on_bad_lines='skip', low_memory=False)
            logger.info(f"   ✓ Đọc CSV: {len(df)} dòng, {len(df.columns)} cột")

            # MẸO CHUẨN HÓA: Ép toàn bộ tên cột về chữ thường để tránh lỗi viết hoa/thường
            df.columns = df.columns.str.strip().str.lower()

            cot_map = {
                'product_id': ['product_id', 'id', 'itemid', '_primarykey'],
                'product_name': ['product_name', 'name', 'title'],
                'price': ['price', 'gia', 'giá'],
                'rating': ['rating', 'stars', 'rating_average', 'ratingstar', 'item_rating'],
                'num_sold': ['num_sold', 'sold', 'quantity_sold', 'luot_ban', 'historicalsold', 'soldcount'],
            }

            for col_standard, col_options in cot_map.items():
                for col_alt in col_options:
                    if col_alt in df.columns and col_standard not in df.columns:
                        df.rename(columns={col_alt: col_standard}, inplace=True)
                        break

            # Nếu dữ liệu thiếu cột giá, ép mặc định 50k để không bị lọc xóa mất
            required_cols = ['product_id', 'product_name', 'price', 'rating', 'num_sold']
            for col in required_cols:
                if col not in df.columns:
                    df[col] = 50000 if col == 'price' else (0 if col in ['rating', 'num_sold'] else 'Unknown_Kaggle')

            df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(50000)
            df['rating'] = pd.to_numeric(df['rating'], errors='coerce').fillna(0)
            df['num_sold'] = pd.to_numeric(df['num_sold'], errors='coerce').fillna(0)

            self.du_lieu_tho = []
            for _, row in df.iterrows():
                gia = float(row['price'])
                item = {
                    'itemid': f"KG_{row['product_id']}",  # Thêm KG_ để ID không bị trùng lặp
                    'name': str(row['product_name']),
                    'price': gia * 100000 if 0 < gia < 1000 else gia,
                    'item_rating': {'rating_average': float(row['rating'])},
                    'sold': int(row['num_sold']),
                }
                self.du_lieu_tho.append(item)

            logger.info(f"   ✓ Trích xuất thành công: {len(self.du_lieu_tho)} sản phẩm Kaggle")
            return len(self.du_lieu_tho) > 0

        except Exception as e:
            logger.error(f"❌ Lỗi xử lý CSV Kaggle: {type(e).__name__} - {str(e)}")
            return False

# ============================================================================
# CLASS: LamSachDuLieu (Merge Tiki + Kaggle)
# ============================================================================

class LamSachDuLieu:
    def __init__(self, du_lieu_tiki: List[Dict], du_lieu_kaggle: List[Dict]):
        self.du_lieu_tiki = du_lieu_tiki
        self.du_lieu_kaggle = du_lieu_kaggle
        self.df = None
        self.nhop = pd.DataFrame()

    def gop_du_lieu(self):
        logger.info("📊 Gộp dữ liệu Tiki + Kaggle...")

        du_lieu_tiki_clean = [{
            'id': str(i.get('id', '')), 'name': i.get('name', ''), 'price': float(i.get('price', 0)),
            'rating_average': float(i.get('rating_average', 0)), 'quantity_sold': extract_quantity_sold(i.get('quantity_sold')),
            'primary_category_path': i.get('primary_category_path', ''), 'url': f"https://tiki.vn/{i.get('url_path', '')}",
            'nen_tang': 'Tiki'
        } for i in self.du_lieu_tiki]

        du_lieu_kaggle_clean = [{
            'id': str(i.get('itemid', '')), 'name': i.get('name', ''),
            'price': float(i.get('price', 0)) / 100000 if i.get('price') and float(i.get('price')) > 10000 else float(i.get('price', 0)),
            'rating_average': float(i.get('item_rating', {}).get('rating_average', 0)),
            'quantity_sold': i.get('sold', 0), 'url': f"https://kaggle.com/dataset/item-{i.get('itemid', '')}",
            'nen_tang': 'Kaggle', 'primary_category_path': 'Kaggle Dataset'
        } for i in self.du_lieu_kaggle]

        df_tiki = pd.DataFrame(du_lieu_tiki_clean)
        df_kaggle = pd.DataFrame(du_lieu_kaggle_clean)

        if not df_tiki.empty:
            df_tiki['nganh_hang'] = df_tiki['primary_category_path'].apply(map_nganh_hang_tiki)

        if not df_kaggle.empty:
            df_kaggle['nganh_hang'] = 'Kaggle Dataset'

        cols_common = ['id', 'name', 'price', 'rating_average', 'quantity_sold', 'url', 'nen_tang', 'nganh_hang']
        self.df = pd.concat([df_tiki[cols_common] if not df_tiki.empty else pd.DataFrame(columns=cols_common),
                             df_kaggle[cols_common] if not df_kaggle.empty else pd.DataFrame(columns=cols_common)], ignore_index=True)

    def xu_ly(self) -> pd.DataFrame:
        self.gop_du_lieu()
        self.df.rename(columns={'id': 'ma_san_pham', 'name': 'ten_san_pham', 'price': 'gia', 'rating_average': 'danh_gia', 'quantity_sold': 'luot_ban'}, inplace=True)

        self.df = self.df.dropna(subset=['ma_san_pham', 'ten_san_pham', 'gia'], how='any')
        self.df['danh_gia'] = self.df['danh_gia'].fillna(0).clip(0, 5)
        self.df['luot_ban'] = self.df['luot_ban'].fillna(0).astype(int)
        self.df['gia'] = pd.to_numeric(self.df['gia'], errors='coerce').fillna(0)
        self.df = self.df[self.df['gia'] > 0]
        self.df = self.df.drop_duplicates(subset=['ma_san_pham'], keep='first')

        if len(self.df) >= 2:
            Q1, Q3 = self.df['gia'].quantile(0.25), self.df['gia'].quantile(0.75)
            IQR = Q3 - Q1
            ngoai_lai_iqr = (self.df['gia'] < Q1 - 1.5 * IQR) | (self.df['gia'] > Q3 + 1.5 * IQR)
            std_gia = self.df['gia'].std()
            ngoai_lai_z = np.abs((self.df['gia'] - self.df['gia'].mean()) / std_gia) > 3.0 if std_gia > 0 else pd.Series(False, index=self.df.index)
            self.df['da_kiem_tra_gia_ao'] = ngoai_lai_iqr | ngoai_lai_z
            self.nhop = self.df[self.df['da_kiem_tra_gia_ao'] == True].copy()

        logger.info(f"✅ DỮ LIỆU ĐÃ CHUẨN HÓA: Tổng {len(self.df)} dòng (Tiki: {len(self.df[self.df['nen_tang']=='Tiki'])}, Kaggle: {len(self.df[self.df['nen_tang']=='Kaggle'])})")
        return self.df

# ============================================================================
# SCRIPT CHÍNH
# ============================================================================

if __name__ == "__main__":
    logger.info("🔷 BƯỚC 1: THU THẬP TIKI")
    bot_tiki = ThuThapTiki()
    bot_tiki.goi_api_tiki_multi()

    logger.info("\n🔶 BƯỚC 2: ĐỌC KAGGLE DATASET")
    doc_kaggle = DocKaggles(csv_path="data.csv")
    doc_kaggle.doc_tu_csv()

    logger.info("\n🧹 BƯỚC 3: LÀM SẠCH")
    lam_sach = LamSachDuLieu(bot_tiki.du_lieu_tho, doc_kaggle.du_lieu_tho)
    df_sach = lam_sach.xu_ly()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    df_sach.to_csv(f"dulieu_tiki_kaggle_v4.3_{timestamp}.csv", index=False, encoding='utf-8-sig')