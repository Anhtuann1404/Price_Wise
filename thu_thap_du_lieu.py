"""
PriceWise - Thu thập & làm sạch dữ liệu sản phẩm TMĐT từ Tiki.

Module này cung cấp 2 lớp chính:
1. ThuThapDuLieu: Gọi API Tiki / đọc file CSV/JSON, lưu dữ liệu thô
2. LamSachDuLieu: Chuẩn hóa, xử lý thiếu/trùng/ngoại lai → dữ liệu sạch

Schema cuối cùng (dữ liệu sạch):
    ma_san_pham, ten_san_pham, nganh_hang, shop, gia, gia_goc,
    ty_le_giam, luot_ban, danh_gia, url, da_kiem_tra_gia_ao
"""

import json
import pandas as pd
import numpy as np
import requests
import time
import logging
from pathlib import Path
from typing import Optional, List, Dict

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ThuThapDuLieu:
    """Thu thập dữ liệu sản phẩm từ API Tiki / đọc CSV/JSON."""

    def __init__(self):
        """Khởi tạo, chuẩn bị headers giả lập trình duyệt."""
        self.du_lieu_tho = []
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/91.0.4472.124 Safari/537.36'
        }
        self.log = logger

    def goi_api_tiki(self, ma_nganh_hang: str, so_trang: int = 2,
                     delay: float = 2.0) -> bool:
        """
        Gọi API Tiki để lấy dữ liệu sản phẩm.

        Args:
            ma_nganh_hang: Mã ngành hàng Tiki (vd: "8322" = Nhà sách)
            so_trang: Số trang cần lấy
            delay: Thời gian chờ giữa các request (giây), tránh rate limit

        Returns:
            True nếu lấy thành công, False nếu lỗi.
        """
        for page in range(1, so_trang + 1):
            try:
                url = (
                    f"https://tiki.vn/api/personalish/v1/blocks/listings"
                    f"?limit=40&category={ma_nganh_hang}&page={page}"
                )

                self.log.info(f"Gọi trang {page}/{so_trang}...")
                response = requests.get(url, headers=self.headers, timeout=10)
                response.raise_for_status()

                data = response.json().get('data', [])
                if not data:
                    self.log.warning(f"Trang {page} trả về dữ liệu trống.")
                else:
                    self.du_lieu_tho.extend(data)
                    self.log.info(
                        f"✓ Trang {page}: lấy được {len(data)} sản phẩm "
                        f"(tổng: {len(self.du_lieu_tho)})"
                    )

                # Trễ hợp lý để không bị chặn
                if page < so_trang:
                    time.sleep(delay)

            except requests.exceptions.RequestException as e:
                self.log.error(f"Lỗi khi gọi trang {page}: {e}")
                return False
            except json.JSONDecodeError as e:
                self.log.error(f"Lỗi parse JSON trang {page}: {e}")
                return False

        return len(self.du_lieu_tho) > 0

    def doc_csv(self, duong_dan: str) -> bool:
        """Đọc dữ liệu từ file CSV."""
        try:
            df = pd.read_csv(duong_dan)
            self.du_lieu_tho = df.to_dict('records')
            self.log.info(f"✓ Đọc CSV: {len(self.du_lieu_tho)} dòng")
            return True
        except Exception as e:
            self.log.error(f"Lỗi đọc CSV: {e}")
            return False

    def doc_json(self, duong_dan: str) -> bool:
        """Đọc dữ liệu từ file JSON."""
        try:
            with open(duong_dan, 'r', encoding='utf-8') as f:
                self.du_lieu_tho = json.load(f)
            self.log.info(f"✓ Đọc JSON: {len(self.du_lieu_tho)} dòng")
            return True
        except Exception as e:
            self.log.error(f"Lỗi đọc JSON: {e}")
            return False

    def luu_du_lieu(self, ten_file_goc: str) -> bool:
        """
        Lưu dữ liệu thô ra file CSV và JSON.

        Args:
            ten_file_goc: Tên file không có phần mở rộng (vd: "dulieu_tiki")

        Returns:
            True nếu lưu thành công
        """
        if not self.du_lieu_tho:
            self.log.warning("Chưa có dữ liệu để lưu!")
            return False

        try:
            df = pd.DataFrame(self.du_lieu_tho)

            # Lưu CSV
            file_csv = f"{ten_file_goc}.csv"
            df.to_csv(file_csv, index=False, encoding='utf-8-sig')
            self.log.info(f"✓ Lưu CSV: {file_csv}")

            # Lưu JSON
            file_json = f"{ten_file_goc}.json"
            df.to_json(
                file_json, orient='records',
                force_ascii=False, indent=2
            )
            self.log.info(f"✓ Lưu JSON: {file_json}")
            return True

        except Exception as e:
            self.log.error(f"Lỗi lưu file: {e}")
            return False


class LamSachDuLieu:
    """
    Làm sạch, chuẩn hóa dữ liệu thô từ Tiki.

    Quy trình:
    1. Ánh xạ cột Tiki → schema PriceWise
    2. Xử lý thiếu/trùng lặp
    3. Ép kiểu dữ liệu
    4. Phát hiện ngoại lai (IQR/Z-score)
    5. Tạo cờ để phân tích riêng
    """

    def __init__(self, du_lieu_tho: List[Dict]):
        """
        Khởi tạo lớp với dữ liệu thô.

        Args:
            du_lieu_tho: Danh sách dict (từ API/CSV/JSON)
        """
        self.du_lieu_tho = du_lieu_tho
        self.df = None
        self.nhop = []  # Danh sách ngoại lai phát hiện được
        self.log = logger

    def anh_xa_cot(self) -> pd.DataFrame:
        """
        Ánh xạ cột Tiki thô → schema PriceWise chuẩn.

        Schema chuẩn:
            - ma_san_pham: ID sản phẩm (từ 'id')
            - ten_san_pham: Tên sản phẩm (từ 'name')
            - nganh_hang: Ngành hàng (từ 'primary_category_path' hoặc 'short_description')
            - shop: Tên shop/người bán (từ 'seller')
            - gia: Giá hiện tại (từ 'price')
            - gia_goc: Giá gốc (từ 'original_price')
            - ty_le_giam: Tỷ lệ giảm (từ 'discount_rate' / 100)
            - luot_ban: Lượt bán (từ 'quantity_sold')
            - danh_gia: Đánh giá trung bình (từ 'rating_average')
            - url: Link sản phẩm (từ 'url_path')
        """
        self.log.info("Bắt đầu ánh xạ cột...")

        df = pd.DataFrame(self.du_lieu_tho)

        # Tạo DataFrame mới với cột chuẩn
        schema_moi = pd.DataFrame()

        # Hàm helper để lấy cột an toàn
        def get_col(df, col_names):
            """Thử lấy cột từ danh sách tên, trả về cột đầu tiên tồn tại."""
            if not isinstance(col_names, list):
                col_names = [col_names]
            for col in col_names:
                if col in df.columns:
                    return df[col]
            return pd.Series([''] * len(df))  # Trả về cột trống nếu không tìm thấy

        # Ánh xạ ID sản phẩm
        schema_moi['ma_san_pham'] = get_col(df, ['id', 'ma_san_pham']).astype(str)

        # Tên sản phẩm
        schema_moi['ten_san_pham'] = get_col(df, ['name', 'ten_san_pham'])

        # Ngành hàng: thử primary_category_path, nếu không có dùng short_description
        if 'primary_category_path' in df.columns:
            # Lấy phần cuối của path (cách dấu '/')
            schema_moi['nganh_hang'] = df['primary_category_path'].apply(
                lambda x: str(x).split('/')[-1] if pd.notna(x) else 'Chưa phân loại'
            )
        else:
            schema_moi['nganh_hang'] = get_col(df, ['nganh_hang']).fillna('Chưa phân loại')

        # Shop/người bán
        schema_moi['shop'] = get_col(df, ['seller', 'shop']).fillna('Tiki')

        # Giá (tính từ price hoặc list_price)
        schema_moi['gia'] = get_col(df, ['price', 'gia']).fillna(0)

        # Giá gốc (original_price hoặc list_price)
        if 'original_price' in df.columns and df['original_price'].notna().any():
            schema_moi['gia_goc'] = df['original_price'].fillna(schema_moi['gia'])
        elif 'list_price' in df.columns:
            schema_moi['gia_goc'] = df['list_price'].fillna(schema_moi['gia'])
        else:
            schema_moi['gia_goc'] = get_col(df, ['gia_goc']).fillna(schema_moi['gia'])

        # Tỷ lệ giảm (discount_rate: chia cho 100)
        if 'discount_rate' in df.columns:
            schema_moi['ty_le_giam'] = df['discount_rate'].fillna(0) / 100
        else:
            # Tính từ giá: (gia_goc - gia) / gia_goc
            gia_goc = schema_moi['gia_goc'].values
            gia = schema_moi['gia'].values
            schema_moi['ty_le_giam'] = np.where(
                gia_goc > 0,
                np.maximum((gia_goc - gia) / gia_goc, 0),
                0
            )

        # Lượt bán (quantity_sold hoặc order_count)
        schema_moi['luot_ban'] = get_col(df, ['quantity_sold', 'order_count', 'luot_ban']).fillna(0)

        # Đánh giá (rating_average hoặc danh_gia)
        schema_moi['danh_gia'] = get_col(df, ['rating_average', 'danh_gia']).fillna(0)

        # URL (url_path hoặc url)
        if 'url_path' in df.columns:
            schema_moi['url'] = 'https://tiki.vn/' + df['url_path'].astype(str)
        else:
            schema_moi['url'] = get_col(df, ['url']).fillna('')

        self.df = schema_moi.reset_index(drop=True)
        self.log.info(f"✓ Ánh xạ thành công: {len(self.df)} dòng, {len(self.df.columns)} cột")
        return self.df

    def xu_ly_thieu_trung(self):
        """
        Xử lý thiếu dữ liệu (NULL) và dòng trùng lặp.

        Chiến lược:
        - Cột quan trọng (ma_san_pham, gia, danh_gia): xóa dòng có NULL
        - Cột phụ (shop, nganh_hang): điền giá trị mặc định
        - Dòng trùng lặp: giữ dòng đầu tiên, xóa bản sao
        """
        if self.df is None:
            self.log.error("Chưa ánh xạ cột. Gọi anh_xa_cot() trước.")
            return

        so_dong_ban_dau = len(self.df)

        # Bước 1: Xóa NULL ở cột quan trọng
        cot_bat_buoc = ['ma_san_pham', 'ten_san_pham', 'gia', 'danh_gia', 'url']
        so_null_truoc = self.df[cot_bat_buoc].isnull().sum().sum()

        self.df = self.df.dropna(subset=cot_bat_buoc, how='any')

        so_null_sau = len(self.df)
        if so_null_truoc > 0:
            self.log.info(
                f"✓ Xóa {so_dong_ban_dau - so_null_sau} dòng có NULL "
                f"ở cột bắt buộc ({so_null_truoc} cell NULL)"
            )

        # Bước 2: Điền giá trị mặc định cho cột phụ
        self.df['shop'] = self.df['shop'].fillna('Tiki')
        self.df['nganh_hang'] = self.df['nganh_hang'].fillna('Chưa phân loại')
        self.df['gia_goc'] = self.df['gia_goc'].fillna(self.df['gia'])
        self.df['ty_le_giam'] = self.df['ty_le_giam'].fillna(0)
        self.df['luot_ban'] = self.df['luot_ban'].fillna(0)

        self.log.info("✓ Điền NULL ở cột phụ với giá trị mặc định")

        # Bước 3: Xóa dòng trùng lặp (dựa trên ma_san_pham)
        so_dong_truoc_dup = len(self.df)
        self.df = self.df.drop_duplicates(subset=['ma_san_pham'], keep='first')
        so_dong_sau_dup = len(self.df)

        if so_dong_truoc_dup > so_dong_sau_dup:
            self.log.info(
                f"✓ Xóa {so_dong_truoc_dup - so_dong_sau_dup} dòng trùng lặp "
                f"(dựa trên ma_san_pham)"
            )

        self.df = self.df.reset_index(drop=True)
        self.log.info(f"→ Sau xử lý thiếu/trùng: {len(self.df)} dòng")

    def ep_kieu_du_lieu(self):
        """
        Ép kiểu dữ liệu cho các cột số.

        Chuyển đổi:
        - gia, gia_goc, ty_le_giam, luot_ban, danh_gia → numeric
        - Xóa ký tự đặc biệt (dấu phẩy, khoảng trắng)
        - Kiểm tra giá hợp lệ (> 0)
        """
        if self.df is None:
            self.log.error("Chưa có DataFrame.")
            return

        self.log.info("Bắt đầu ép kiểu dữ liệu...")

        # Hàm phụ: chuyển đổi an toàn sang số
        def to_numeric(col, name):
            """Chuyển đổi cột sang số, bỏ qua lỗi."""
            self.df[col] = pd.to_numeric(
                self.df[col], errors='coerce'
            ).fillna(0)

            # Nếu là tỷ lệ, giới hạn trong [0, 1]
            if col == 'ty_le_giam':
                self.df[col] = self.df[col].clip(0, 1)

            # Nếu là đánh giá, giới hạn trong [0, 5]
            if col == 'danh_gia':
                self.df[col] = self.df[col].clip(0, 5)

        # Chuyển đổi các cột số
        cot_so = ['gia', 'gia_goc', 'ty_le_giam', 'luot_ban', 'danh_gia']
        for col in cot_so:
            to_numeric(col, col)

        # Chuyển sang kiểu int cho lượt bán
        self.df['luot_ban'] = self.df['luot_ban'].astype(int)

        # Chuyển sang kiểu categorical cho nganh_hang, shop
        self.df['nganh_hang'] = self.df['nganh_hang'].astype('category')
        self.df['shop'] = self.df['shop'].astype('category')

        # Kiểm tra giá hợp lệ (phải > 0)
        gia_0 = (self.df['gia'] <= 0).sum()
        if gia_0 > 0:
            self.log.warning(f"⚠ {gia_0} sản phẩm có giá ≤ 0 (sẽ được loại bỏ)")
            self.df = self.df[self.df['gia'] > 0]

        self.log.info(f"✓ Ép kiểu thành công | Còn {len(self.df)} dòng hợp lệ")

    def xu_ly_ngoai_lai_va_gan_co(self,
                                  iqr_multiplier: float = 1.5,
                                  z_score_threshold: float = 3.0):
        """
        Phát hiện ngoại lai (outlier) bằng IQR và Z-score.

        Chiến lược:
        - IQR: ngoài Q1 - 1.5*IQR đến Q3 + 1.5*IQR
        - Z-score: |z| > 3.0 (rất bất thường)
        - Gắn cờ (flag) thay vì xóa → phục vụ phân tích "giảm giá ảo"

        Args:
            iqr_multiplier: Hệ số nhân IQR (mặc định 1.5)
            z_score_threshold: Ngưỡng Z-score (mặc định 3.0)
        """
        if self.df is None:
            self.log.error("Chưa có DataFrame.")
            return

        self.log.info("Bắt đầu phát hiện ngoại lai...")

        # Khởi tạo cột cờ ngoại lai
        self.df['da_kiem_tra_gia_ao'] = False

        # Áp dụng IQR cho cột giá
        Q1 = self.df['gia'].quantile(0.25)
        Q3 = self.df['gia'].quantile(0.75)
        IQR = Q3 - Q1

        lower_bound = Q1 - iqr_multiplier * IQR
        upper_bound = Q3 + iqr_multiplier * IQR

        ngoai_lai_iqr = (self.df['gia'] < lower_bound) | (self.df['gia'] > upper_bound)

        # Tính Z-score cho giá
        mean_gia = self.df['gia'].mean()
        std_gia = self.df['gia'].std()
        z_score = np.abs((self.df['gia'] - mean_gia) / (std_gia + 1e-10))
        ngoai_lai_zscore = z_score > z_score_threshold

        # Gắn cờ ngoại lai
        self.df.loc[ngoai_lai_iqr | ngoai_lai_zscore, 'da_kiem_tra_gia_ao'] = True

        so_ngoai_lai = self.df['da_kiem_tra_gia_ao'].sum()
        phan_tram = (so_ngoai_lai / len(self.df)) * 100

        self.log.info(
            f"✓ Phát hiện {so_ngoai_lai} ngoại lai ({phan_tram:.1f}%) "
            f"(IQR: {ngoai_lai_iqr.sum()}, Z-score: {ngoai_lai_zscore.sum()})"
        )

        # Ghi nhớ danh sách ngoại lai
        self.nhop = self.df[self.df['da_kiem_tra_gia_ao'] == True].copy()

        if len(self.nhop) > 0:
            self.log.info(f"  → Lưu {len(self.nhop)} ngoại lai để phân tích riêng")

    def lay_du_lieu_sach(self) -> pd.DataFrame:
        """
        Trả về DataFrame đã chuẩn hóa hoàn toàn.

        Quy trình hoàn chỉnh:
        1. Ánh xạ cột
        2. Xử lý thiếu/trùng
        3. Ép kiểu
        4. Phát hiện ngoại lai
        """
        if self.df is None:
            self.anh_xa_cot()

        self.xu_ly_thieu_trung()
        self.ep_kieu_du_lieu()
        self.xu_ly_ngoai_lai_va_gan_co()

        self.log.info(
            f"\n{'=' * 60}"
            f"\n✓ DỮ LIỆU ĐÃ CHUẨN HÓA HOÀN TOÀN\n"
            f"  • Tổng sản phẩm: {len(self.df)}\n"
            f"  • Cột: {list(self.df.columns)}\n"
            f"  • Ngành hàng: {self.df['nganh_hang'].nunique()} loại\n"
            f"  • Shop: {self.df['shop'].nunique()} shop\n"
            f"  • Giá trung bình: {self.df['gia'].mean():,.0f} đ\n"
            f"  • Đánh giá TB: {self.df['danh_gia'].mean():.2f} ⭐\n"
            f"{'=' * 60}\n"
        )

        return self.df

    def lay_ngoai_lai(self) -> pd.DataFrame:
        """Trả về DataFrame chứa các sản phẩm ngoại lai."""
        if len(self.nhop) == 0:
            return pd.DataFrame()
        return self.nhop

    def xuat_bao_cao_chat_luong(self, ten_file: str = "bao_cao_chat_luong.txt"):
        """
        Xuất báo cáo chất lượng dữ liệu.

        Ghi lại: số NULL xóa, số trùng lặp, số ngoại lai, thống kê cơ bản.
        """
        if self.df is None:
            self.log.error("Chưa có dữ liệu sạch.")
            return

        with open(ten_file, 'w', encoding='utf-8') as f:
            f.write("BÁO CÁO CHẤT LƯỢNG DỮ LIỆU - PriceWise\n")
            f.write("=" * 60 + "\n\n")

            f.write("1. THỐNG KÊ CHUNG\n")
            f.write(f"   Tổng sản phẩm: {len(self.df)}\n")
            f.write(f"   Số cột: {len(self.df.columns)}\n")
            f.write(f"   Ngành hàng: {self.df['nganh_hang'].nunique()}\n")
            f.write(f"   Shop: {self.df['shop'].nunique()}\n\n")

            f.write("2. THỐNG KÊ GIÁ\n")
            f.write(f"   Min: {self.df['gia'].min():,.0f} đ\n")
            f.write(f"   Max: {self.df['gia'].max():,.0f} đ\n")
            f.write(f"   Trung bình: {self.df['gia'].mean():,.0f} đ\n")
            f.write(f"   Trung vị: {self.df['gia'].median():,.0f} đ\n")
            f.write(f"   Độ lệch chuẩn: {self.df['gia'].std():,.0f} đ\n\n")

            f.write("3. THỐNG KÊ ĐÁNH GIÁ\n")
            f.write(f"   Trung bình: {self.df['danh_gia'].mean():.2f} ⭐\n")
            f.write(f"   Min: {self.df['danh_gia'].min()}\n")
            f.write(f"   Max: {self.df['danh_gia'].max()}\n\n")

            f.write("4. NGOẠI LAI PHÁT HIỆN\n")
            f.write(f"   Số sản phẩm: {self.df['da_kiem_tra_gia_ao'].sum()}\n")
            f.write(f"   Tỷ lệ: {(self.df['da_kiem_tra_gia_ao'].sum() / len(self.df) * 100):.1f}%\n\n")

            f.write("5. PHÂN BỐ THEO NGÀNH HÀNG\n")
            phan_bo = self.df['nganh_hang'].value_counts()
            for nganh, so_luong in phan_bo.items():
                f.write(f"   {nganh}: {so_luong} sản phẩm\n")

        self.log.info(f"✓ Báo cáo chất lượng: {ten_file}")


# ============================================================================
# SCRIPT CHÍNH - DEMO QUY TRÌNH
# ============================================================================

if __name__ == "__main__":
    # Cách 1: Thu thập từ API Tiki (nếu server còn hoạt động)
    print("\n" + "=" * 60)
    print("DEMO: QUY TRÌNH THU THẬP & LÀM SẠCH DỮ LIỆU")
    print("=" * 60 + "\n")

    # bot = ThuThapDuLieu()
    # Gọi API Tiki ngành sách (8322)
    # success = bot.goi_api_tiki(ma_nganh_hang="8322", so_trang=2)
    # if success:
    #     bot.luu_du_lieu("dulieu_nhasach_tiki")
    #     lam_sach = LamSachDuLieu(bot.du_lieu_tho)
    # else:
    #     print("⚠ Không thể gọi API. Dùng dữ liệu CSV thay thế.\n")
    #     lam_sach = LamSachDuLieu([])

    # Cách 2: Đọc từ CSV hiện có (cho demo)
    print("Đọc dữ liệu từ CSV hiện có (thực tế)...\n")
    bot = ThuThapDuLieu()
    bot.doc_csv("dulieu_nhasach_tiki.csv")

    # Khởi tạo lớp làm sạch
    lam_sach = LamSachDuLieu(bot.du_lieu_tho)

    # Chạy quy trình hoàn chỉnh
    df_sach = lam_sach.lay_du_lieu_sach()

    # In một vài dòng mẫu
    print("\n>>> Mẫu dữ liệu sạch (5 dòng đầu):\n")
    print(df_sach.head()[['ma_san_pham', 'ten_san_pham', 'gia', 'danh_gia',
                          'luot_ban', 'da_kiem_tra_gia_ao']].to_string())

    # Xuất báo cáo
    lam_sach.xuat_bao_cao_chat_luong("bao_cao_chat_luong.txt")

    # Lưu dữ liệu sạch
    df_sach.to_csv("dulieu_nhasach_tiki_sach.csv", index=False, encoding='utf-8-sig')
    print("\n✓ Dữ liệu sạch đã lưu: dulieu_nhasach_tiki_sach.csv")

    # Lưu ngoại lai
    ngoai_lai = lam_sach.lay_ngoai_lai()
    if len(ngoai_lai) > 0:
        ngoai_lai.to_csv("ngoai_lai.csv", index=False, encoding='utf-8-sig')
        print(f"✓ Ngoại lai đã lưu: ngoai_lai.csv ({len(ngoai_lai)} dòng)")
