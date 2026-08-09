"""
PriceWise - Module Học máy (Thành viên C - ML Engineer)
=========================================================

Nội dung:
  - PhanTichGia   : chấm điểm "value score" (chuẩn hóa MinMax + trọng số)
                    và phân cụm KMeans (chọn k bằng Elbow + Silhouette).
  - TroLyMuaSam   : lớp trợ lý mua sắm - nhận sản phẩm/ngân sách, trả về
                    (1) đánh giá giá theo percentile trong ngành hàng,
                    (2) phân khúc (cụm) sản phẩm thuộc về,
                    (3) top 3 sản phẩm thay thế rẻ hơn kèm link thật.

Toàn bộ gợi ý của TroLyMuaSam chỉ tra cứu trên DataFrame tĩnh đã thu thập
sẵn (không gọi API sống) để đảm bảo tái lập được khi chấm bài.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import MinMaxScaler

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Các đặc trưng dùng để chấm value score / phân cụm.
# Lưu ý: "gia" càng THẤP thì càng tốt -> sẽ đảo dấu (1 - scaled) khi tính điểm.
DAC_TRUNG = ["gia", "danh_gia", "luot_ban", "ty_le_giam"]

# Số sản phẩm tối thiểu trong 1 ngành hàng để percentile/gợi ý còn ý nghĩa
# thống kê. Dữ liệu mẫu hiện có nhiều ngành chỉ 1-3 sản phẩm nên phải có
# ngưỡng này để tránh kết luận sai lệch (vd "percentile 100%" chỉ vì có 1 sp).
NGUONG_SO_SP_NGANH = 5


# =============================================================================
# LỚP PHANTICHGIA - phần Value Score + Phân cụm KMeans
# =============================================================================

class PhanTichGia:
    """
    Tính "value score" và phân cụm sản phẩm bằng KMeans trên dữ liệu đã
    làm sạch (đầu ra của LamSachDuLieu).

    Attributes:
        df: DataFrame sản phẩm, có thêm cột 'value_score' và 'cum' sau khi
            gọi tinh_value_score() và phan_cum_kmeans().
    """

    def __init__(self, df: pd.DataFrame):
        if df is None or df.empty:
            raise ValueError("DataFrame đầu vào rỗng hoặc None.")
        thieu_cot = [c for c in DAC_TRUNG if c not in df.columns]
        if thieu_cot:
            raise ValueError(f"DataFrame thiếu cột bắt buộc: {thieu_cot}")

        self.df = df.copy().reset_index(drop=True)
        self.scaler: Optional[MinMaxScaler] = None
        self.kmeans_model: Optional[KMeans] = None
        self.trong_so: dict = {}
        self.ten_cum: dict[int, str] = {}
        self.mo_ta_cum: dict[int, str] = {}
        self._da_chuan_hoa = False

    # -------------------------------------------------------------------
    # BƯỚC 1: CHUẨN HÓA (dùng chung cho value score & KMeans)
    # -------------------------------------------------------------------
    def _chuan_hoa_dac_trung(self) -> pd.DataFrame:
        """Chuẩn hóa min-max 4 đặc trưng, đảo dấu cột 'gia'. Idempotent."""
        try:
            self.scaler = MinMaxScaler()
            X = self.df[DAC_TRUNG].astype(float).values
            X_scaled = self.scaler.fit_transform(X)

            df_scaled = pd.DataFrame(
                X_scaled, columns=[f"{c}_sc" for c in DAC_TRUNG], index=self.df.index
            )
            # Giá thấp = tốt -> đảo dấu để "càng cao càng tốt" như 3 cột kia
            df_scaled["gia_sc"] = 1 - df_scaled["gia_sc"]

            for col in df_scaled.columns:
                self.df[col] = df_scaled[col]

            self._da_chuan_hoa = True
            return df_scaled
        except Exception as loi:
            logger.error(f"Lỗi khi chuẩn hóa đặc trưng: {loi}")
            raise

    # -------------------------------------------------------------------
    # BƯỚC 2: VALUE SCORE
    # -------------------------------------------------------------------
    def tinh_value_score(self, trong_so: Optional[dict] = None) -> pd.DataFrame:
        """
        Tính điểm value_score (0-100) = tổ hợp tuyến tính có trọng số của
        4 đặc trưng đã chuẩn hóa min-max: gia (đảo dấu), danh_gia, luot_ban,
        ty_le_giam.

        Giải thích trọng số mặc định (có thể truyền tay khi gọi hàm):
            - gia       0.40  -> yếu tố quan trọng nhất: "value" nghĩa là
                                 rẻ so với mặt bằng chung ngành hàng.
            - danh_gia  0.30  -> chất lượng/sự hài lòng người mua trước đó,
                                 quan trọng gần bằng giá vì giá rẻ mà rating
                                 thấp thì không còn là "hời".
            - luot_ban  0.20  -> tín hiệu "được thị trường kiểm chứng"
                                 (nhiều người đã mua & không hoàn trả ồ ạt),
                                 trọng số thấp hơn vì lượt bán lệch phải rất
                                 mạnh (vài sản phẩm bán chạy áp đảo phần còn
                                 lại) nên chỉ nên là yếu tố phụ trợ.
            - ty_le_giam 0.10 -> trọng số thấp nhất, CỐ Ý: tỷ lệ giảm giá dễ
                                 bị "làm ảo" (đẩy giá gốc rồi giảm sâu - xem
                                 Câu hỏi 4 của đề tài), nên chỉ đóng vai trò
                                 cộng điểm nhẹ chứ không phải căn cứ chính.

        Args:
            trong_so: dict 4 khóa {'gia','danh_gia','luot_ban','ty_le_giam'}
                      cộng lại phải bằng 1.0 (dung sai 1e-6).

        Returns:
            DataFrame self.df đã có thêm cột 'value_score'.
        """
        mac_dinh = {"gia": 0.40, "danh_gia": 0.30, "luot_ban": 0.20, "ty_le_giam": 0.10}
        trong_so = trong_so or mac_dinh

        if abs(sum(trong_so.values()) - 1.0) > 1e-6:
            raise ValueError(f"Tổng trọng số phải = 1.0, hiện tại = {sum(trong_so.values())}")
        if set(trong_so.keys()) != set(DAC_TRUNG):
            raise ValueError(f"trong_so phải có đúng 4 khóa: {DAC_TRUNG}")

        if not self._da_chuan_hoa:
            self._chuan_hoa_dac_trung()

        self.df["value_score"] = (
            trong_so["gia"] * self.df["gia_sc"]
            + trong_so["danh_gia"] * self.df["danh_gia_sc"]
            + trong_so["luot_ban"] * self.df["luot_ban_sc"]
            + trong_so["ty_le_giam"] * self.df["ty_le_giam_sc"]
        ) * 100

        self.trong_so = trong_so
        logger.info(
            f"value_score: min={self.df['value_score'].min():.1f}  "
            f"max={self.df['value_score'].max():.1f}  "
            f"mean={self.df['value_score'].mean():.1f}"
        )
        return self.df

    # -------------------------------------------------------------------
    # BƯỚC 3: CHỌN K TỐI ƯU (Elbow + Silhouette)
    # -------------------------------------------------------------------
    def tim_k_toi_uu(self, k_min: int = 2, k_max: int = 8, random_state: int = 42) -> pd.DataFrame:
        """
        Chạy KMeans với k chạy từ k_min..k_max, ghi lại inertia (cho Elbow)
        và silhouette score cho mỗi k. Không tự chọn k thay người dùng -
        trả về bảng để người dùng (hoặc phan_cum_kmeans) tự quyết định,
        đúng tinh thần "quy trình khoa học, không chọn k tùy ý".

        Returns:
            DataFrame cột ['k', 'inertia', 'silhouette'].
        """
        if not self._da_chuan_hoa:
            self._chuan_hoa_dac_trung()

        n_mau = len(self.df)
        k_max = min(k_max, n_mau - 1)  # KMeans cần k < số mẫu
        if k_max < k_min:
            raise ValueError(
                f"Không đủ dữ liệu ({n_mau} sản phẩm) để thử k từ {k_min} đến {k_max}."
            )

        X = self.df[[f"{c}_sc" for c in DAC_TRUNG]].values
        ket_qua = []
        for k in range(k_min, k_max + 1):
            try:
                km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
                nhan = km.fit_predict(X)
                sil = silhouette_score(X, nhan)
                ket_qua.append({"k": k, "inertia": km.inertia_, "silhouette": sil})
            except Exception as loi:
                logger.warning(f"Bỏ qua k={k} do lỗi: {loi}")

        df_kq = pd.DataFrame(ket_qua)
        self.bang_chon_k = df_kq
        return df_kq

    # -------------------------------------------------------------------
    # BƯỚC 4: PHÂN CỤM CHÍNH THỨC
    # -------------------------------------------------------------------
    def phan_cum_kmeans(self, k: Optional[int] = None, random_state: int = 42) -> pd.DataFrame:
        """
        Phân cụm KMeans chính thức trên 4 đặc trưng đã chuẩn hóa.

        Args:
            k: số cụm. Nếu None -> tự chọn k có silhouette cao nhất trong
               bảng tim_k_toi_uu() (chạy tự động nếu chưa có).

        Returns:
            self.df đã có thêm cột 'cum' (int) và 'ten_cum' (str, chân dung).
        """
        if not self._da_chuan_hoa:
            self._chuan_hoa_dac_trung()

        if k is None:
            if not hasattr(self, "bang_chon_k"):
                self.tim_k_toi_uu()
            k = int(self.bang_chon_k.loc[self.bang_chon_k["silhouette"].idxmax(), "k"])
            logger.info(f"Tự động chọn k={k} (silhouette cao nhất)")

        X = self.df[[f"{c}_sc" for c in DAC_TRUNG]].values
        self.kmeans_model = KMeans(n_clusters=k, random_state=random_state, n_init=10)
        self.df["cum"] = self.kmeans_model.fit_predict(X)

        self._dat_ten_cum()
        self.df["ten_cum"] = self.df["cum"].map(self.ten_cum)
        return self.df

    def _dat_ten_cum(self) -> None:
        """
        Đặt tên & mô tả "chân dung" cho từng cụm dựa trên HẠNG TƯƠNG ĐỐI
        giữa các cụm với nhau (không so với một ngưỡng toàn cục cố định),
        để tên gọi luôn phân biệt được nhau dù k lớn hay dữ liệu lệch mạnh
        (vd một vài sản phẩm bán chạy áp đảo phần còn lại).

        Quy trình:
          1. Xếp hạng các cụm theo gia_tb -> chia 3 bậc giá (Rẻ/Tầm trung/Đắt).
          2. Trong mỗi bậc giá, so rating_tb với TRUNG VỊ rating của các cụm
             cùng bậc -> "Đáng tin/Xắt ra miếng" (rating >= trung vị) hay
             "Đáng ngờ/Cần cân nhắc" (rating < trung vị).
          3. Nếu vẫn trùng tên (hiếm, khi >1 cụm cùng bậc giá + cùng phía
             rating), phân biệt thêm bằng lượt bán (Hạng 1, Hạng 2, ...
             theo value_score) để đảm bảo KHÔNG có 2 cụm trùng tên.
        """
        thong_ke = self.df.groupby("cum")[DAC_TRUNG + ["value_score"]].mean()
        n_cum = len(thong_ke)

        # Bậc giá: xếp hạng cụm theo gia_tb tăng dần rồi chia 3 phần gần đều
        hang_gia = thong_ke["gia"].rank(method="first").astype(int)  # 1..n_cum
        so_bac = min(3, n_cum)
        bien = np.array_split(np.arange(1, n_cum + 1), so_bac)
        def bac_cua(hang, danh_sach_bien):
            for i, nhom in enumerate(danh_sach_bien):
                if hang in nhom:
                    return i
            return len(danh_sach_bien) - 1
        bac_gia = hang_gia.apply(lambda h: bac_cua(h, bien))
        ten_bac = {0: "Rẻ", 1: "Tầm trung", 2: "Đắt"} if so_bac == 3 else (
            {0: "Rẻ", 1: "Đắt"} if so_bac == 2 else {0: "Tầm trung"}
        )

        ten_tam: dict[int, str] = {}
        mota_tam: dict[int, str] = {}

        for bac in bac_gia.unique():
            cum_trong_bac = bac_gia[bac_gia == bac].index
            rating_trungvi = thong_ke.loc[cum_trong_bac, "danh_gia"].median()

            for cum_id in cum_trong_bac:
                hang = thong_ke.loc[cum_id]
                nhan_gia = ten_bac[bac]
                rating_tot = hang["danh_gia"] >= rating_trungvi

                if nhan_gia == "Rẻ":
                    hau_to, mota = (
                        ("Đáng tin",
                         "Giá thuộc nhóm thấp nhất và rating tốt hơn các cụm giá "
                         "thấp khác - đây là nhóm 'hời thật sự', ưu tiên gợi ý hàng đầu.")
                        if rating_tot else
                        ("Đáng ngờ",
                         "Giá thấp nhưng rating kém hơn các cụm giá thấp khác - "
                         "nghi ngờ chất lượng hoặc giảm giá ảo, cần cảnh báo người dùng.")
                    )
                elif nhan_gia == "Đắt":
                    hau_to, mota = (
                        ("Xắt ra miếng",
                         "Giá thuộc nhóm cao nhất nhưng rating cũng cao hơn các cụm "
                         "giá cao khác - hợp lý cho người ưu tiên chất lượng.")
                        if rating_tot else
                        ("Cần cân nhắc",
                         "Giá thuộc nhóm cao nhất nhưng rating không tương xứng "
                         "so với các cụm giá cao khác - nên ưu tiên tìm thay thế.")
                    )
                else:
                    hau_to, mota = (
                        ("Ổn định",
                         "Giá và rating ở mức trung bình, cân bằng, ít rủi ro - "
                         "lựa chọn an toàn khi không có nhu cầu đặc biệt.")
                        if rating_tot else
                        ("Cần xem xét",
                         "Giá tầm trung nhưng rating dưới trung vị nhóm tầm trung - "
                         "còn nhiều lựa chọn tốt hơn cùng tầm giá.")
                    )

                ten_tam[cum_id] = f"{nhan_gia} - {hau_to}"
                mota_tam[cum_id] = mota

        # Đảm bảo không có 2 cụm trùng tên: nếu trùng, gắn thêm hạng theo value_score
        dem = pd.Series(ten_tam).value_counts()
        ten_trung = dem[dem > 1].index.tolist()
        for ten in ten_trung:
            cum_trung = [cid for cid, t in ten_tam.items() if t == ten]
            # hạng cao hơn value_score -> số nhỏ hơn (ưu tiên hơn)
            xep_hang = thong_ke.loc[cum_trung, "value_score"].rank(ascending=False, method="first")
            for cid in cum_trung:
                ten_tam[cid] = f"{ten} (nhóm {int(xep_hang[cid])})"

        self.ten_cum = ten_tam
        self.mo_ta_cum = mota_tam

    def bao_cao_chan_dung_cum(self) -> pd.DataFrame:
        """Bảng tổng hợp chân dung từng cụm (dùng để đưa vào báo cáo/Streamlit)."""
        if "cum" not in self.df.columns:
            raise RuntimeError("Chưa phân cụm. Gọi phan_cum_kmeans() trước.")

        bang = self.df.groupby("cum").agg(
            ten_cum=("ten_cum", "first"),
            so_sp=("ma_san_pham", "count"),
            gia_tb=("gia", "mean"),
            rating_tb=("danh_gia", "mean"),
            luot_ban_tb=("luot_ban", "mean"),
            ty_le_giam_tb=("ty_le_giam", "mean"),
            value_score_tb=("value_score", "mean"),
        ).reset_index()
        bang["mo_ta"] = bang["cum"].map(self.mo_ta_cum)
        return bang.sort_values("value_score_tb", ascending=False).reset_index(drop=True)


# =============================================================================
# LỚP TROLYMUASAM
# =============================================================================

@dataclass
class KetQuaDanhGia:
    """Kết quả trả về của TroLyMuaSam.danh_gia_san_pham()."""
    ma_san_pham: int
    ten_san_pham: str
    gia: float
    nganh_hang: str
    percentile_gia: Optional[float]  # None nếu ngành hàng quá ít sản phẩm
    ghi_chu_percentile: str
    cum: Optional[int]
    ten_cum: Optional[str]
    value_score: Optional[float]
    top3_thay_the: pd.DataFrame = field(repr=False)
    ghi_chu_thay_the: str = ""


class TroLyMuaSam:
    """
    Trợ lý mua sắm thông minh - lớp mà Streamlit (Tab 3) gọi trực tiếp.

    QUAN TRỌNG: mọi gợi ý CHỈ tra cứu trên DataFrame tĩnh đã thu thập sẵn
    (self.df), KHÔNG gọi API sống. Điều này đảm bảo:
      - tái lập được khi giảng viên chạy lại bài (Restart & Run All);
      - an toàn, không phụ thuộc mạng/IP lúc demo;
      - đúng phạm vi đã cam kết: "rẻ hơn trong tập dữ liệu đã thu thập",
        không quảng cáo "rẻ nhất toàn mạng".
    """

    def __init__(self, df: pd.DataFrame):
        """
        Args:
            df: DataFrame đã qua PhanTichGia (bắt buộc có cột 'value_score'
                và 'cum'). Ném lỗi rõ ràng nếu thiếu, để lỗi cấu hình bị bắt
                sớm thay vì lỗi ngầm lúc demo.
        """
        cot_bat_buoc = ["ma_san_pham", "ten_san_pham", "nganh_hang", "gia",
                         "danh_gia", "luot_ban", "url", "value_score", "cum"]
        thieu = [c for c in cot_bat_buoc if c not in df.columns]
        if thieu:
            raise ValueError(
                f"DataFrame thiếu cột {thieu}. Hãy chạy PhanTichGia."
                f"tinh_value_score() và .phan_cum_kmeans() trước khi khởi tạo TroLyMuaSam."
            )
        self.df = df.copy().reset_index(drop=True)

    # -------------------------------------------------------------------
    def _percentile_gia_trong_nganh(self, ma_san_pham: int) -> tuple[Optional[float], str]:
        """
        Percentile giá của sản phẩm SO VỚI các sản phẩm CÙNG ngành hàng.
        percentile càng THẤP = càng rẻ so với ngành (0% = rẻ nhất ngành).

        Trả về (None, ghi_chu) nếu ngành hàng có quá ít sản phẩm
        (< NGUONG_SO_SP_NGANH) để percentile có ý nghĩa thống kê.
        """
        sp = self.df.loc[self.df["ma_san_pham"] == ma_san_pham].iloc[0]
        cung_nganh = self.df[self.df["nganh_hang"] == sp["nganh_hang"]]

        if len(cung_nganh) < NGUONG_SO_SP_NGANH:
            return None, (
                f"Ngành '{sp['nganh_hang']}' chỉ có {len(cung_nganh)} sản phẩm "
                f"trong dữ liệu - không đủ để tính percentile đáng tin cậy."
            )

        percentile = (cung_nganh["gia"] < sp["gia"]).mean() * 100
        return round(percentile, 1), (
            f"Rẻ hơn {percentile:.0f}% trong tổng số {len(cung_nganh)} sản phẩm "
            f"cùng ngành '{sp['nganh_hang']}'."
        )

    # -------------------------------------------------------------------
    def _top3_thay_the(self, ma_san_pham: int, sai_lech_rating_toi_da: float = 0.5
                        ) -> tuple[pd.DataFrame, str]:
        """
        Tìm tối đa 3 sản phẩm THAY THẾ rẻ hơn, cùng ngành hàng, rating
        không thấp hơn quá `sai_lech_rating_toi_da` so với sản phẩm gốc,
        xếp theo value_score giảm dần.

        Nếu không đủ 3 sản phẩm thỏa điều kiện chặt (cùng ngành + rẻ hơn +
        rating tương đương), nới lỏng dần và ghi rõ trong ghi chú, thay vì
        trả về danh sách rỗng hoặc gợi ý sai lệch âm thầm.
        """
        sp = self.df.loc[self.df["ma_san_pham"] == ma_san_pham].iloc[0]

        ung_vien = self.df[
            (self.df["nganh_hang"] == sp["nganh_hang"])
            & (self.df["ma_san_pham"] != ma_san_pham)
            & (self.df["gia"] < sp["gia"])
            & (self.df["danh_gia"] >= sp["danh_gia"] - sai_lech_rating_toi_da)
        ].copy()

        ghi_chu = "Cùng ngành hàng, rẻ hơn, rating tương đương."
        if len(ung_vien) < 3:
            # Nới điều kiện rating trước
            ung_vien2 = self.df[
                (self.df["nganh_hang"] == sp["nganh_hang"])
                & (self.df["ma_san_pham"] != ma_san_pham)
                & (self.df["gia"] < sp["gia"])
            ].copy()
            if len(ung_vien2) > len(ung_vien):
                ung_vien = ung_vien2
                ghi_chu = "Cùng ngành hàng, rẻ hơn (đã nới điều kiện rating do ít lựa chọn)."

        if len(ung_vien) == 0:
            return ung_vien.head(0), (
                f"Không tìm thấy sản phẩm nào rẻ hơn trong ngành "
                f"'{sp['nganh_hang']}' trong tập dữ liệu hiện có."
            )

        ung_vien["pct_re_hon"] = (1 - ung_vien["gia"] / sp["gia"]) * 100
        top3 = ung_vien.sort_values("value_score", ascending=False).head(3)

        if len(top3) < 3:
            ghi_chu += f" Chỉ tìm được {len(top3)}/3 lựa chọn phù hợp trong dữ liệu."

        return top3[["ma_san_pham", "ten_san_pham", "gia", "danh_gia", "luot_ban",
                      "value_score", "pct_re_hon", "url"]].reset_index(drop=True), ghi_chu

    # -------------------------------------------------------------------
    def danh_gia_san_pham(self, ma_san_pham: int) -> KetQuaDanhGia:
        """
        API chính #1: đánh giá một sản phẩm cụ thể theo mã sản phẩm.

        Trả về KetQuaDanhGia gồm 3 phần theo đúng yêu cầu:
          (1) percentile giá trong ngành hàng,
          (2) cụm/phân khúc KMeans sản phẩm thuộc về,
          (3) top 3 sản phẩm thay thế rẻ hơn kèm link thật.

        Raises:
            ValueError: nếu không tìm thấy mã sản phẩm trong dữ liệu.
        """
        khop = self.df[self.df["ma_san_pham"] == ma_san_pham]
        if khop.empty:
            raise ValueError(f"Không tìm thấy sản phẩm có mã {ma_san_pham} trong dữ liệu.")

        sp = khop.iloc[0]
        percentile, ghi_chu_pct = self._percentile_gia_trong_nganh(ma_san_pham)
        top3, ghi_chu_thaythe = self._top3_thay_the(ma_san_pham)

        return KetQuaDanhGia(
            ma_san_pham=int(sp["ma_san_pham"]),
            ten_san_pham=sp["ten_san_pham"],
            gia=float(sp["gia"]),
            nganh_hang=sp["nganh_hang"],
            percentile_gia=percentile,
            ghi_chu_percentile=ghi_chu_pct,
            cum=int(sp["cum"]),
            ten_cum=sp["ten_cum"],
            value_score=round(float(sp["value_score"]), 1),
            top3_thay_the=top3,
            ghi_chu_thay_the=ghi_chu_thaythe,
        )

    # -------------------------------------------------------------------
    def goi_y_theo_ngan_sach(self, ngan_sach: float, nganh_hang: Optional[str] = None,
                              top_n: int = 5) -> pd.DataFrame:
        """
        API chính #2: nhập ngân sách (+ ngành hàng tùy chọn) -> trả về
        top sản phẩm "hời nhất" (value_score cao nhất) trong tầm giá.

        Args:
            ngan_sach: số tiền tối đa (VNĐ).
            nganh_hang: lọc theo ngành hàng cụ thể, None = tất cả ngành.
            top_n: số sản phẩm trả về.

        Returns:
            DataFrame top_n sản phẩm, rỗng nếu không có sản phẩm nào trong
            ngân sách (không raise lỗi, vì đây là kết quả hợp lệ về mặt
            nghiệp vụ, chỉ là không có lựa chọn).
        """
        if ngan_sach <= 0:
            raise ValueError("Ngân sách phải > 0.")

        ung_vien = self.df[self.df["gia"] <= ngan_sach]
        if nganh_hang is not None:
            ung_vien = ung_vien[ung_vien["nganh_hang"] == nganh_hang]

        if ung_vien.empty:
            logger.info(f"Không có sản phẩm nào <= {ngan_sach:,.0f}đ (ngành: {nganh_hang}).")
            return ung_vien

        return ung_vien.sort_values("value_score", ascending=False).head(top_n)[
            ["ma_san_pham", "ten_san_pham", "nganh_hang", "gia", "danh_gia",
             "luot_ban", "value_score", "ten_cum", "url"]
        ].reset_index(drop=True)


# =============================================================================
# DEMO CHẠY TRỰC TIẾP (dùng để kiểm thử nhanh & sinh số liệu cho báo cáo)
# =============================================================================

if __name__ == "__main__":
    df_sach = pd.read_csv("dulieu_sach_v3.csv")

    print("=" * 70)
    print("1) VALUE SCORE")
    print("=" * 70)
    pt = PhanTichGia(df_sach)
    pt.tinh_value_score()
    print(pt.df[["ten_san_pham", "gia", "danh_gia", "luot_ban", "ty_le_giam",
                 "value_score"]].sort_values("value_score", ascending=False).head(5).to_string(index=False))

    print("\n" + "=" * 70)
    print("2) CHỌN K (ELBOW + SILHOUETTE)")
    print("=" * 70)
    bang_k = pt.tim_k_toi_uu(k_min=2, k_max=8)
    print(bang_k.to_string(index=False))

    print("\n" + "=" * 70)
    print("3) PHÂN CỤM KMEANS")
    print("=" * 70)
    pt.phan_cum_kmeans()
    print(pt.bao_cao_chan_dung_cum().to_string(index=False))

    print("\n" + "=" * 70)
    print("4) TRỢ LÝ MUA SẮM - DEMO")
    print("=" * 70)
    tro_ly = TroLyMuaSam(pt.df)

    mau_sp = pt.df.iloc[0]["ma_san_pham"]
    ket_qua = tro_ly.danh_gia_san_pham(mau_sp)
    print(f"\n--- Đánh giá sản phẩm: {ket_qua.ten_san_pham} ---")
    print(f"Giá: {ket_qua.gia:,.0f}đ | Ngành: {ket_qua.nganh_hang}")
    print(f"Percentile: {ket_qua.percentile_gia} | {ket_qua.ghi_chu_percentile}")
    print(f"Cụm: {ket_qua.cum} - {ket_qua.ten_cum}")
    print(f"Value score: {ket_qua.value_score}")
    print(f"Ghi chú thay thế: {ket_qua.ghi_chu_thay_the}")
    if not ket_qua.top3_thay_the.empty:
        print(ket_qua.top3_thay_the.to_string(index=False))

    print("\n--- Gợi ý theo ngân sách 100,000đ ---")
    goi_y = tro_ly.goi_y_theo_ngan_sach(100_000)
    print(goi_y.to_string(index=False) if not goi_y.empty else "Không có sản phẩm phù hợp.")

    # Lưu dữ liệu đã gắn value_score + cụm để Streamlit (Tab 2, Tab 3) dùng
    pt.df.to_csv("dulieu_sach_v3_ml.csv", index=False, encoding="utf-8-sig")
    print("\n✓ Đã lưu dulieu_sach_v3_ml.csv (dữ liệu + value_score + cụm)")
