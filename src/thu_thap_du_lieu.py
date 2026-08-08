"""
PriceWise v3.0 - Thu thập & Làm sạch Dữ liệu TMĐT từ Tiki.

🔄 Cập nhật chính:
  ✅ Mở rộng: 1000+ sản phẩm từ 3-4 ngành hàng
  ✅ Fix luot_ban: Parse dict {"text": "Đã bán X", "value": X} → số
  ✅ Fix nganh_hang: Map ID → Tên tiếng Việt
  ✅ Fix shop: Extract từ current_seller (không phải seller=null)
  ✅ Tối ưu: Batch processing, error handling, logging chi tiết

Cấu trúc:
  - ThuThapDuLieu: Thu thập từ API (multi-category, retry logic)
  - LamSachDuLieu: Làm sạch (extract, ép kiểu, phát hiện ngoại lai)
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


# ============================================================================
# LOGGING & CONFIGURATION
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# Dictionary map: Mã ngành Tiki → Tên tiếng Việt
NGANH_HANG_MAPPING = {
    # Sách
    "8322": "Sách tiếng Việt",
    "316": "Sách ngoại văn",
    "1084": "Truyện tranh/Manga",
    "67998": "Sách thiếu nhi",
    "871": "Tô màu - Luyện chữ",
    "67867": "Đồ chơi học tập",
    "6750": "Đồ chơi thương hiệu",
    "67996": "Sản phẩm cho bé",

    # Thời trang
    "11": "Áo nam",
    "12": "Quần nam",
    "13": "Giày nam",
    "14": "Áo nữ",
    "15": "Quần nữ",
    "16": "Giày nữ",
    "17": "Phụ kiện thời trang",

    # Điện tử
    "1": "Điện thoại",
    "2": "Tablet",
    "3": "Laptop",
    "4": "Tai nghe",
    "5": "Phụ kiện điện thoại",

    # Sức khỏe & Làm đẹp
    "385": "Mỹ phẩm",
    "664": "Chăm sóc da",
    "1754": "Máy massage",
    "2250": "Dụng cụ làm đẹp",
    "853": "Vitamin & Thực phẩm bổ sung",
    "847": "Chăm sóc cơ thể",
    "840": "Kem dưỡng ẩm",
    "843": "Mặt nạ/Serum",
    "844": "Tẩy rửa mặt",
    "845": "Nước hoa",

    # Gia dụng
    "9725": "Đèn chiếu sáng",
    "67869": "Thiết bị nhà bếp",
    "67871": "Thiết bị phòng tắm",
    "67915": "Nệm & Gối",
}

# Mã ngành phổ biến (để gọi API)
NGANH_HANG_THU_TAP = [
    ("8322", "Sách tiếng Việt", 5),          # 5 trang = ~200 sản phẩm
    ("316", "Sách ngoại văn", 3),            # 3 trang = ~120 sản phẩm
    ("1084", "Truyện tranh/Manga", 4),       # 4 trang = ~160 sản phẩm
    ("11", "Áo nam", 3),                     # 3 trang = ~120 sản phẩm
    ("1", "Điện thoại", 4),                  # 4 trang = ~160 sản phẩm
    ("385", "Mỹ phẩm", 3),                   # 3 trang = ~120 sản phẩm
]

# Endpoint constants
TIKI_API_BASE = "https://tiki.vn/api/personalish/v1/blocks/listings"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def extract_quantity_sold(value) -> int:
    """
    Trích xuất số lượng bán từ cột quantity_sold.

    Input có thể là:
    - Dict: {"text": "Đã bán 273", "value": 273}
    - Integer: 273
    - String: "273" hoặc "Đã bán 273"
    - NaN/None

    Output: Integer ≥ 0
    """
    try:
        # Nếu là dict
        if isinstance(value, dict):
            return int(value.get('value', 0))

        # Nếu là số
        if isinstance(value, (int, float)):
            return int(max(value, 0))

        # Nếu là string
        if isinstance(value, str):
            # Tìm số đầu tiên trong string (VD: "Đã bán 273" → 273)
            match = re.search(r'\d+', value)
            if match:
                return int(match.group())

        return 0
    except Exception as e:
        logger.warning(f"⚠ Lỗi parse quantity_sold: {value} → {type(e).__name__}")
        return 0


def extract_shop_name(seller_info) -> str:
    """
    Trích xuất tên shop từ current_seller hoặc seller field.

    Input có thể là:
    - Dict: {"name": "Shop Chính Hãng", ...}
    - String: "Shop Chính Hãng"
    - NaN/None

    Output: String (tên shop hoặc "Tiki" default)
    """
    try:
        # Nếu là dict
        if isinstance(seller_info, dict):
            return seller_info.get('name', 'Tiki').strip()

        # Nếu là string
        if isinstance(seller_info, str) and seller_info.strip():
            return seller_info.strip()

        return 'Tiki'
    except Exception:
        return 'Tiki'


def map_nganh_hang(category_id: str) -> str:
    """Map mã ngành (ID) → Tên tiếng Việt."""
    if not category_id:
        return "Chưa phân loại"

    category_id = str(category_id).strip()
    return NGANH_HANG_MAPPING.get(category_id, f"Ngành {category_id}")


# ============================================================================
# CLASS: ThuThapDuLieu
# ============================================================================

class ThuThapDuLieu:
    """Thu thập dữ liệu sản phẩm từ API Tiki (multi-category)."""

    def __init__(self, max_retries: int = 3, timeout: int = 10):
        """
        Args:
            max_retries: Số lần thử lại khi lỗi
            timeout: Timeout cho request (giây)
        """
        self.du_lieu_tho = []
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/120.0.0.0 Safari/537.36'
        }
        self.max_retries = max_retries
        self.timeout = timeout
        self.thong_ke = {"thanhcong": 0, "loi": 0, "trungdup": set()}

    def goi_api_tiki_multi(self, nganh_hang_list: List[Tuple[str, str, int]] = None,
                          delay: float = 1.5) -> bool:
        """
        Gọi API Tiki để lấy dữ liệu từ nhiều ngành hàng.

        Args:
            nganh_hang_list: Danh sách (ma_nganh, ten_nganh, so_trang)
            delay: Thời gian chờ giữa các request (giây)

        Returns:
            True nếu lấy được ≥500 sản phẩm, False nếu lỗi.
        """
        if nganh_hang_list is None:
            nganh_hang_list = NGANH_HANG_THU_TAP

        tong_sp = 0
        logger.info(f"🔄 Bắt đầu gọi API từ {len(nganh_hang_list)} ngành hàng...")
        logger.info(f"   Mục tiêu: ≥500 sản phẩm (1000+ tối ưu)")

        for ma_nganh, ten_nganh, so_trang in nganh_hang_list:
            logger.info(f"\n📥 Ngành: {ten_nganh} (Mã: {ma_nganh}) | {so_trang} trang")

            sp_nganh = 0
            for page in range(1, so_trang + 1):
                try:
                    # Gọi API với retry logic
                    success, data = self._call_api_with_retry(
                        ma_nganh, page
                    )

                    if not success or not data:
                        logger.warning(f"   ⚠ Trang {page}: Không có dữ liệu")
                        continue

                    # Lưu dữ liệu
                    self.du_lieu_tho.extend(data)
                    sp_nganh += len(data)
                    tong_sp += len(data)

                    logger.info(f"   ✓ Trang {page}: {len(data)} sản phẩm | "
                               f"Tổng ngành: {sp_nganh} | Tổng chung: {tong_sp}")

                    # Trễ để tránh rate limit
                    if page < so_trang:
                        time.sleep(delay)

                except Exception as e:
                    logger.error(f"   ❌ Trang {page}: {type(e).__name__}: {e}")
                    self.thong_ke["loi"] += 1

            logger.info(f"   → Kết thúc: {sp_nganh} sản phẩm từ {ten_nganh}")

        # Loại bỏ trùng lặp dựa trên ma_san_pham
        tong_truoc = len(self.du_lieu_tho)
        ma_sp_duy_nhat = set()
        du_lieu_unique = []

        for item in self.du_lieu_tho:
            ma_sp = item.get('id')
            if ma_sp not in ma_sp_duy_nhat:
                ma_sp_duy_nhat.add(ma_sp)
                du_lieu_unique.append(item)

        self.du_lieu_tho = du_lieu_unique
        tong_sau = len(self.du_lieu_tho)

        logger.info(f"\n{'='*70}")
        logger.info(f"✅ HOÀN THÀNH THU THẬP")
        logger.info(f"   • Tổng sản phẩm (trước loại trùng): {tong_truoc}")
        logger.info(f"   • Tổng sản phẩm (sau loại trùng): {tong_sau}")
        logger.info(f"   • Sản phẩm bị trùng: {tong_truoc - tong_sau}")
        logger.info(f"{'='*70}")

        return tong_sau >= 500

    def _call_api_with_retry(self, ma_nganh: str, page: int) -> Tuple[bool, List]:
        """
        Gọi API Tiki với retry logic.

        Returns:
            (success, data_list)
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                url = (
                    f"{TIKI_API_BASE}"
                    f"?limit=40&category={ma_nganh}&page={page}"
                )

                response = requests.get(
                    url,
                    headers=self.headers,
                    timeout=self.timeout
                )
                response.raise_for_status()

                data = response.json().get('data', [])
                self.thong_ke["thanhcong"] += 1
                return True, data

            except requests.exceptions.Timeout:
                logger.debug(f"   (Lần {attempt}/{self.max_retries}) Timeout, thử lại...")
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)  # Exponential backoff
            except requests.exceptions.ConnectionError as e:
                logger.debug(f"   (Lần {attempt}/{self.max_retries}) Lỗi kết nối, thử lại...")
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
            except json.JSONDecodeError:
                logger.warning(f"   ⚠ Lỗi parse JSON trang {page}")
                return False, []
            except Exception as e:
                logger.error(f"   ❌ Lỗi: {type(e).__name__}: {e}")
                return False, []

        logger.error(f"   ❌ Thất bại sau {self.max_retries} lần thử")
        return False, []

    def doc_csv(self, duong_dan: str) -> bool:
        """Đọc dữ liệu từ file CSV."""
        try:
            df = pd.read_csv(duong_dan)
            self.du_lieu_tho = df.to_dict('records')
            logger.info(f"✓ Đọc CSV: {len(self.du_lieu_tho)} dòng từ {duong_dan}")
            return True
        except FileNotFoundError:
            logger.error(f"❌ File không tìm thấy: {duong_dan}")
            return False
        except Exception as e:
            logger.error(f"❌ Lỗi đọc CSV: {e}")
            return False

    def luu_du_lieu(self, ten_file_goc: str) -> bool:
        """Lưu dữ liệu thô ra CSV + JSON."""
        if not self.du_lieu_tho:
            logger.warning("⚠ Chưa có dữ liệu để lưu!")
            return False

        try:
            df = pd.DataFrame(self.du_lieu_tho)

            # CSV
            file_csv = f"{ten_file_goc}.csv"
            df.to_csv(file_csv, index=False, encoding='utf-8-sig')
            logger.info(f"✓ Lưu CSV: {file_csv} ({len(df)} dòng)")

            # JSON
            file_json = f"{ten_file_goc}.json"
            df.to_json(file_json, orient='records', force_ascii=False, indent=2)
            logger.info(f"✓ Lưu JSON: {file_json}")

            return True

        except Exception as e:
            logger.error(f"❌ Lỗi lưu file: {e}")
            return False


# ============================================================================
# CLASS: LamSachDuLieu
# ============================================================================

class LamSachDuLieu:
    """Làm sạch & chuẩn hóa dữ liệu từ Tiki."""

    def __init__(self, du_lieu_tho: List[Dict]):
        """Khởi tạo với dữ liệu thô."""
        self.du_lieu_tho = du_lieu_tho
        self.df = None
        self.nhop = pd.DataFrame()
        self.log = logger

    def anh_xa_cot(self) -> pd.DataFrame:
        """
        Ánh xạ cột Tiki thô → schema PriceWise chuẩn.

        Schema (11 cột):
            ma_san_pham, ten_san_pham, nganh_hang, shop,
            gia, gia_goc, ty_le_giam, luot_ban, danh_gia, url,
            da_kiem_tra_gia_ao
        """
        self.log.info("📍 Bước 1: Ánh xạ cột...")

        df = pd.DataFrame(self.du_lieu_tho)

        # Kiểm tra nếu đã là schema chuẩn (v2)
        if all(col in df.columns for col in ['ma_san_pham', 'ten_san_pham', 'gia']):
            self.log.info("   → Phát hiện: Dữ liệu đã chuẩn hóa (v2)")
            # Thêm cột thiếu nếu cần
            if 'da_kiem_tra_gia_ao' not in df.columns:
                df['da_kiem_tra_gia_ao'] = False
            self.df = df
            return self.df

        schema_moi = pd.DataFrame()

        # ID sản phẩm
        schema_moi['ma_san_pham'] = df['id'].astype(str) if 'id' in df.columns else ''

        # Tên sản phẩm
        schema_moi['ten_san_pham'] = df['name'] if 'name' in df.columns else ''

        # Ngành hàng: Map ID → Tên Việt
        if 'primary_category_path' in df.columns:
            # Lấy ID ngành cuối cùng (cách dấu /)
            category_ids = df['primary_category_path'].apply(
                lambda x: str(x).split('/')[-1] if pd.notna(x) else ''
            )
            schema_moi['nganh_hang'] = category_ids.apply(map_nganh_hang)
        else:
            schema_moi['nganh_hang'] = 'Chưa phân loại'

        # Shop: Thử current_seller trước, sau đó seller
        if 'current_seller' in df.columns:
            schema_moi['shop'] = df['current_seller'].apply(extract_shop_name)
        elif 'seller' in df.columns:
            schema_moi['shop'] = df['seller'].apply(extract_shop_name)
        else:
            schema_moi['shop'] = 'Tiki'

        # Giá (price)
        gia_col = df['price'] if 'price' in df.columns else df.get('gia', 0)
        schema_moi['gia'] = pd.to_numeric(gia_col, errors='coerce').fillna(0)

        # Giá gốc
        if 'original_price' in df.columns:
            schema_moi['gia_goc'] = pd.to_numeric(
                df['original_price'], errors='coerce'
            ).fillna(schema_moi['gia'])
        elif 'list_price' in df.columns:
            schema_moi['gia_goc'] = pd.to_numeric(
                df['list_price'], errors='coerce'
            ).fillna(schema_moi['gia'])
        else:
            schema_moi['gia_goc'] = schema_moi['gia']

        # Tỷ lệ giảm
        if 'discount_rate' in df.columns:
            schema_moi['ty_le_giam'] = (
                pd.to_numeric(df['discount_rate'], errors='coerce').fillna(0) / 100
            )
        else:
            # Tính từ giá: (gia_goc - gia) / gia_goc
            gia_goc = schema_moi['gia_goc'].values
            gia = schema_moi['gia'].values
            schema_moi['ty_le_giam'] = np.where(
                gia_goc > 0,
                np.maximum((gia_goc - gia) / gia_goc, 0),
                0
            )

        # Lượt bán: Extract từ dict "{'text': '...', 'value': X}"
        if 'quantity_sold' in df.columns:
            schema_moi['luot_ban'] = df['quantity_sold'].apply(
                extract_quantity_sold
            ).astype(int)
        else:
            schema_moi['luot_ban'] = 0

        # Đánh giá
        schema_moi['danh_gia'] = pd.to_numeric(
            df.get('rating_average', 0), errors='coerce'
        ).fillna(0)

        # URL
        if 'url_path' in df.columns:
            schema_moi['url'] = 'https://tiki.vn/' + df['url_path'].astype(str)
        else:
            schema_moi['url'] = df.get('url', '')

        self.df = schema_moi.reset_index(drop=True)

        self.log.info(f"   ✓ Ánh xạ thành công: {len(self.df)} dòng, "
                     f"{len(self.df.columns)} cột")

        return self.df

    def xu_ly_thieu_trung(self):
        """Xử lý thiếu dữ liệu & trùng lặp."""
        if self.df is None:
            self.log.error("❌ Chưa ánh xạ cột")
            return

        self.log.info("📍 Bước 2: Xử lý thiếu dữ liệu & trùng lặp...")

        so_dong_truoc = len(self.df)

        # Bước 1: Xóa NULL ở cột bắt buộc
        cot_bat_buoc = ['ma_san_pham', 'ten_san_pham', 'gia']
        self.df = self.df.dropna(subset=cot_bat_buoc, how='any')

        so_dong_sau = len(self.df)
        if so_dong_truoc > so_dong_sau:
            self.log.info(f"   • Xóa {so_dong_truoc - so_dong_sau} dòng NULL")

        # Bước 2: Điền mặc định cho cột phụ
        self.df['shop'] = self.df['shop'].fillna('Tiki').astype('category')
        self.df['nganh_hang'] = self.df['nganh_hang'].fillna(
            'Chưa phân loại'
        ).astype('category')
        self.df['gia_goc'] = self.df['gia_goc'].fillna(self.df['gia'])
        self.df['ty_le_giam'] = self.df['ty_le_giam'].fillna(0)
        self.df['luot_ban'] = self.df['luot_ban'].fillna(0).astype(int)
        self.df['danh_gia'] = self.df['danh_gia'].fillna(0)

        self.log.info(f"   ✓ Điền NULL với giá trị mặc định")

        # Bước 3: Xóa trùng lặp
        so_dong_truoc_dup = len(self.df)
        self.df = self.df.drop_duplicates(subset=['ma_san_pham'], keep='first')
        so_dong_sau_dup = len(self.df)

        if so_dong_truoc_dup > so_dong_sau_dup:
            self.log.info(f"   • Xóa {so_dong_truoc_dup - so_dong_sau_dup} "
                         f"dòng trùng lặp")

        self.df = self.df.reset_index(drop=True)
        self.log.info(f"   ✓ Sau xử lý: {len(self.df)} dòng")

    def ep_kieu_du_lieu(self):
        """Ép kiểu dữ liệu cho các cột số."""
        if self.df is None:
            self.log.error("❌ Chưa có DataFrame")
            return

        self.log.info("📍 Bước 3: Ép kiểu dữ liệu...")

        # Chuyển sang numeric (đã làm ở anh_xa_cot)
        # Chỉ cần clipping để đảm bảo khoảng hợp lệ

        self.df['danh_gia'] = self.df['danh_gia'].clip(0, 5)
        self.df['ty_le_giam'] = self.df['ty_le_giam'].clip(0, 1)
        self.df['luot_ban'] = self.df['luot_ban'].astype(int)

        # Kiểm tra giá hợp lệ
        gia_0 = (self.df['gia'] <= 0).sum()
        if gia_0 > 0:
            self.log.warning(f"   ⚠ {gia_0} sản phẩm có giá ≤ 0 (sẽ xóa)")
            self.df = self.df[self.df['gia'] > 0]

        self.log.info(f"   ✓ Ép kiểu thành công | {len(self.df)} dòng hợp lệ")

    def xu_ly_ngoai_lai_va_gan_co(self, iqr_multiplier: float = 1.5,
                                  z_score_threshold: float = 3.0):
        """Phát hiện ngoại lai bằng IQR + Z-score."""
        if self.df is None:
            self.log.error("❌ Chưa có DataFrame")
            return

        self.log.info("📍 Bước 4: Phát hiện ngoại lai...")

        self.df['da_kiem_tra_gia_ao'] = False

        # IQR
        Q1 = self.df['gia'].quantile(0.25)
        Q3 = self.df['gia'].quantile(0.75)
        IQR = Q3 - Q1

        lower_bound = Q1 - iqr_multiplier * IQR
        upper_bound = Q3 + iqr_multiplier * IQR

        ngoai_lai_iqr = (self.df['gia'] < lower_bound) | (
            self.df['gia'] > upper_bound
        )

        # Z-score
        mean_gia = self.df['gia'].mean()
        std_gia = self.df['gia'].std()
        z_score = np.abs((self.df['gia'] - mean_gia) / (std_gia + 1e-10))
        ngoai_lai_zscore = z_score > z_score_threshold

        # Gắn cờ
        self.df.loc[ngoai_lai_iqr | ngoai_lai_zscore, 'da_kiem_tra_gia_ao'] = True

        so_ngoai_lai = self.df['da_kiem_tra_gia_ao'].sum()
        phan_tram = (so_ngoai_lai / len(self.df)) * 100

        self.log.info(f"   ✓ Phát hiện {so_ngoai_lai} ngoại lai "
                     f"({phan_tram:.1f}%)")
        self.log.info(f"     - IQR: {ngoai_lai_iqr.sum()} sản phẩm")
        self.log.info(f"     - Z-score: {ngoai_lai_zscore.sum()} sản phẩm")

        self.nhop = self.df[self.df['da_kiem_tra_gia_ao'] == True].copy()

    def lay_du_lieu_sach(self) -> pd.DataFrame:
        """Chạy toàn bộ quy trình làm sạch."""
        if self.df is None:
            self.anh_xa_cot()

        self.xu_ly_thieu_trung()
        self.ep_kieu_du_lieu()
        self.xu_ly_ngoai_lai_va_gan_co()

        self.log.info(f"\n{'='*70}")
        self.log.info(f"✅ DỮ LIỆU ĐÃ CHUẨN HÓA HOÀN TOÀN")
        self.log.info(f"{'='*70}")
        self.log.info(f"  📊 Tổng sản phẩm: {len(self.df):,}")
        self.log.info(f"  📚 Ngành hàng: {self.df['nganh_hang'].nunique()} loại")
        self.log.info(f"  🏪 Shop: {self.df['shop'].nunique()} shop")
        self.log.info(f"  💰 Giá: {self.df['gia'].min():,.0f} - "
                     f"{self.df['gia'].max():,.0f} đ (TB: {self.df['gia'].mean():,.0f} đ)")
        self.log.info(f"  ⭐ Đánh giá: {self.df['danh_gia'].mean():.2f}")
        self.log.info(f"  🚩 Ngoại lai: {self.df['da_kiem_tra_gia_ao'].sum()} "
                     f"({self.df['da_kiem_tra_gia_ao'].sum()/len(self.df)*100:.1f}%)")
        self.log.info(f"{'='*70}\n")

        return self.df

    def lay_ngoai_lai(self) -> pd.DataFrame:
        """Trả về DataFrame chứa sản phẩm ngoại lai."""
        return self.nhop

    def xuat_bao_cao_chat_luong(self, ten_file: str = "bao_cao_chat_luong_v3.txt"):
        """Xuất báo cáo chất lượng chi tiết."""
        if self.df is None:
            self.log.error("❌ Chưa có dữ liệu")
            return

        with open(ten_file, 'w', encoding='utf-8') as f:
            f.write("BÁO CÁO CHẤT LƯỢNG DỮ LIỆU - PriceWise v3.0\n")
            f.write("=" * 70 + "\n\n")

            f.write("1. THỐNG KÊ CHUNG\n")
            f.write(f"   Tổng sản phẩm: {len(self.df):,}\n")
            f.write(f"   Số cột: {len(self.df.columns)}\n")
            f.write(f"   Ngành hàng: {self.df['nganh_hang'].nunique()}\n")
            f.write(f"   Shop: {self.df['shop'].nunique()}\n\n")

            f.write("2. THỐNG KÊ GIÁ\n")
            f.write(f"   Min: {self.df['gia'].min():,.0f} đ\n")
            f.write(f"   Max: {self.df['gia'].max():,.0f} đ\n")
            f.write(f"   Trung bình: {self.df['gia'].mean():,.0f} đ\n")
            f.write(f"   Trung vị: {self.df['gia'].median():,.0f} đ\n")
            f.write(f"   Std: {self.df['gia'].std():,.0f} đ\n\n")

            f.write("3. THỐNG KÊ LƯỢT BÁN\n")
            f.write(f"   Min: {self.df['luot_ban'].min()}\n")
            f.write(f"   Max: {self.df['luot_ban'].max()}\n")
            f.write(f"   Trung bình: {self.df['luot_ban'].mean():.1f}\n")
            f.write(f"   Trung vị: {self.df['luot_ban'].median():.0f}\n\n")

            f.write("4. THỐNG KÊ ĐÁNH GIÁ\n")
            f.write(f"   Trung bình: {self.df['danh_gia'].mean():.2f} ⭐\n")
            f.write(f"   Min: {self.df['danh_gia'].min()}\n")
            f.write(f"   Max: {self.df['danh_gia'].max()}\n\n")

            f.write("5. NGOẠI LAI PHÁT HIỆN\n")
            f.write(f"   Số sản phẩm: {self.df['da_kiem_tra_gia_ao'].sum()}\n")
            f.write(f"   Tỷ lệ: {self.df['da_kiem_tra_gia_ao'].sum() / len(self.df) * 100:.1f}%\n\n")

            f.write("6. TOP 10 SHOP (THEO SỐ LƯỢNG)\n")
            top_shop = self.df['shop'].value_counts().head(10)
            for shop, count in top_shop.items():
                f.write(f"   {shop}: {count} sản phẩm\n")
            f.write("\n")

            f.write("7. PHÂN BỐ THEO NGÀNH HÀNG\n")
            phan_bo = self.df['nganh_hang'].value_counts()
            for nganh, count in phan_bo.items():
                phan_tram = count / len(self.df) * 100
                f.write(f"   {nganh}: {count} sản phẩm ({phan_tram:.1f}%)\n")

        self.log.info(f"✓ Báo cáo: {ten_file}")


# ============================================================================
# SCRIPT CHÍNH
# ============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("🚀 PRICEWISE v3.0 - THU THẬP & LÀM SẠCH DỮ LIỆU TIKI")
    print("=" * 70 + "\n")

    # ==================== OPTION 1: GỌI API ====================
    logger.info("🌐 Gọi API Tiki...")
    bot = ThuThapDuLieu()
    success = bot.goi_api_tiki_multi()
    if success:
        bot.luu_du_lieu("../data/dulieu_tiki_1000sp")
        lam_sach = LamSachDuLieu(bot.du_lieu_tho)
    else:
        logger.warning("❌ API gọi không thành công. Dùng CSV hiện có.\n")
        bot = ThuThapDuLieu()
        bot.doc_csv("../data/dulieu_nhasach_tiki.csv")
        lam_sach = LamSachDuLieu(bot.du_lieu_tho)

    # ==================== LÀM SẠCH ====================
    logger.info("\n🧹 Bắt đầu làm sạch dữ liệu...\n")
    df_sach = lam_sach.lay_du_lieu_sach()

    # ==================== XUẤT DỮ LIỆU ====================
    logger.info("\n💾 Xuất dữ liệu...\n")

    df_sach.to_csv("../data/dulieu_sach_v3.csv", index=False, encoding='utf-8-sig')
    logger.info(f"✓ CSV sạch: ../data/dulieu_sach_v3.csv")

    df_sach.to_json("../data/dulieu_sach_v3.json", orient='records', force_ascii=False, indent=2)
    logger.info(f"✓ JSON sạch: ../data/dulieu_sach_v3.json")

    ngoai_lai = lam_sach.lay_ngoai_lai()
    if len(ngoai_lai) > 0:
        ngoai_lai.to_csv("../data/ngoai_lai_v3.csv", index=False, encoding='utf-8-sig')
        logger.info(f"✓ Ngoại lai: ../data/ngoai_lai_v3.csv ({len(ngoai_lai)} dòng)")

    lam_sach.xuat_bao_cao_chat_luong("../docs/bao_cao_chat_luong_v3.txt")

    logger.info("\n📋 Mẫu dữ liệu sạch (5 dòng đầu):\n")
    print(df_sach[['ma_san_pham', 'ten_san_pham', 'nganh_hang', 'shop', 'gia', 'luot_ban', 'danh_gia']].head().to_string())
    logger.info("\n✅ HOÀN THÀNH! Tất cả file đã lưu.")