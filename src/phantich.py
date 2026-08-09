import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import scipy.stats as stats
import os
import warnings
warnings.filterwarnings('ignore')

# ==========================================
# 1. ĐỌC DỮ LIỆU ĐÃ LÀM SẠCH CỦA A
# ==========================================
# Dùng thẳng file A đã làm sạch (dulieu_sach_v3.csv) -> đã có sẵn nganh_hang
# đúng tên tiếng Việt, luot_ban dạng số, và cờ da_kiem_tra_gia_ao (ngoại lai /
# nghi ngờ giảm giá ảo). Giữ NGUYÊN tên cột gốc (shop, danh_gia, ty_le_giam...)
# để khớp 100% với schema đang dùng trong streamlit_app.py của D/C.
thu_muc_hien_tai = os.path.dirname(os.path.abspath(__file__))
duong_dan_file = os.path.join(thu_muc_hien_tai, '..', 'data', 'dulieu_sach_v3.csv')
df = pd.read_csv(duong_dan_file)
df_clean = df.copy()

print("Đang xử lý làm sạch dữ liệu...")
print(f"Số sản phẩm: {len(df_clean)} | Số ngành hàng: {df_clean['nganh_hang'].nunique()}")

# Fake tạm 2 cột của Thành viên C (ML) để code không bị lỗi khi chạy trước
# TODO: xóa 2 dòng dưới khi C bàn giao value_score / cum_kmeans thật.
df_clean['value_score'] = np.random.uniform(50, 100, len(df_clean))
df_clean['cum_kmeans'] = np.random.choice(['Giá rẻ', 'Tầm trung', 'Cao cấp'], len(df_clean))

# ==========================================
# 2. CLASS PHÂN TÍCH THỐNG KÊ
# ==========================================
# Đổi tên từ PhanTichGia -> PhanTichThongKe để không đụng tên với class
# PhanTichGia bên streamlit_app.py (C viết, chuyên value_score + KMeans).
#
# Mỗi hàm vẽ biểu đồ KHÔNG còn tự plt.show() nữa mà return fig (từ
# plt.subplots()) -> bên Streamlit chỉ cần gọi:
#   st.pyplot(pt_thongke.cau_1_phan_phoi_nganh_hang())
# là biểu đồ render thẳng vào trang web, không bị bung cửa sổ rời.
class PhanTichThongKe:
    def __init__(self, df):
        self.df = df

    def cau_1_phan_phoi_nganh_hang(self):
        print("\n--- CÂU 1: PHÂN PHỐI GIÁ THEO NGÀNH HÀNG ---")
        stats_df = self.df.groupby('nganh_hang')['gia'].agg(
            phuong_sai='var', IQR=lambda x: x.quantile(0.75) - x.quantile(0.25)
        ).reset_index()
        stats_df = stats_df.sort_values('phuong_sai', ascending=False)
        print(stats_df.head())

        top_nganh = self.df['nganh_hang'].value_counts().nlargest(5).index
        df_top = self.df[self.df['nganh_hang'].isin(top_nganh)]
        groups = [df_top[df_top['nganh_hang'] == nganh]['gia'] for nganh in top_nganh]

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.boxplot(groups, tick_labels=top_nganh, patch_artist=True)
        ax.set_title('Phân phối giá theo Top 5 Ngành hàng (Thực tế)')
        ax.set_ylabel('Giá (VNĐ)')
        ax.tick_params(axis='x', rotation=15)
        fig.tight_layout()
        return fig

    def cau_2_tuong_quan_spearman(self):
        print("\n--- CÂU 2: TƯƠNG QUAN ---")
        corr, p_value = stats.spearmanr(self.df['ty_le_giam'], self.df['luot_ban'])
        print(f"Spearman (% Giảm giá & Lượt bán): {corr:.3f}, P-value: {p_value:.3e}")

        fig, ax = plt.subplots(figsize=(9, 6))
        scatter = ax.scatter(self.df['ty_le_giam'] * 100, self.df['luot_ban'],
                              c=self.df['danh_gia'], cmap='viridis', alpha=0.6)
        ax.set_title('Tương quan % Giảm giá và Lượt bán (Dữ liệu Tiki)')
        ax.set_xlabel('Phần trăm giảm giá (%)')
        ax.set_ylabel('Lượt bán')
        fig.colorbar(scatter, ax=ax).set_label('Điểm đánh giá')
        return fig

    def cau_3_kiem_dinh_mann_whitney(self):
        print("\n--- CÂU 3: KIỂM ĐỊNH MANN-WHITNEY U (so sánh giá giữa 2 nhóm) ---")
        # Đúng định hướng khoa học ban đầu (Câu 5 trong kế hoạch): so sánh
        # GIÁ giữa 2 nhóm (thay vì lượt bán giữa 2 mức giảm giá như bản cũ).
        # Ưu tiên so 2 ngành hàng nhiều sản phẩm nhất; nếu data chỉ có 1
        # ngành hàng (tuỳ đợt thu thập của A) thì tự chuyển sang so 2 shop
        # nhiều sản phẩm nhất; nếu vẫn không đủ thì so giá giữa nhóm giảm
        # giá sâu (>20%) và giảm giá ít/không giảm trong CÙNG ngành đó -
        # luôn đảm bảo có kết quả chạy được, không phụ thuộc vào việc data
        # đang đa dạng ngành/shop tới đâu.
        nhan_a = nhan_b = None
        gia_a = gia_b = None
        tieu_de = ""

        top2_nganh = self.df['nganh_hang'].value_counts().nlargest(2)
        if len(top2_nganh) >= 2:
            nhan_a, nhan_b = top2_nganh.index[0], top2_nganh.index[1]
            gia_a = self.df[self.df['nganh_hang'] == nhan_a]['gia']
            gia_b = self.df[self.df['nganh_hang'] == nhan_b]['gia']
            tieu_de = f"Ngành hàng: {nhan_a} vs {nhan_b}"
        else:
            top2_shop = self.df['shop'].value_counts().nlargest(2)
            if len(top2_shop) >= 2:
                nhan_a, nhan_b = top2_shop.index[0], top2_shop.index[1]
                gia_a = self.df[self.df['shop'] == nhan_a]['gia']
                gia_b = self.df[self.df['shop'] == nhan_b]['gia']
                tieu_de = f"Shop: {nhan_a} vs {nhan_b}"
            else:
                # Dự phòng cuối: chỉ 1 ngành + 1 shop -> so giá theo mức giảm giá
                nhan_a, nhan_b = "Giảm giá > 20%", "Giảm giá <= 20%"
                gia_a = self.df[self.df['ty_le_giam'] > 0.2]['gia']
                gia_b = self.df[self.df['ty_le_giam'] <= 0.2]['gia']
                tieu_de = "Mức giảm giá (do data chỉ có 1 ngành hàng/1 shop)"
                print("[Lưu ý] Data hiện chỉ có 1 ngành hàng và 1 shop -> đổi sang "
                      "so sánh giá theo mức giảm giá thay vì theo ngành/shop.")

        stat, p_value = stats.mannwhitneyu(gia_a, gia_b, alternative='two-sided')
        print(f"So sánh: {tieu_de} (n1={len(gia_a)}, n2={len(gia_b)})")
        print(f"Chỉ số U: {stat:.2f}, P-value: {p_value:.4f}")
        if p_value < 0.05:
            print("Kết luận: Có sự khác biệt ý nghĩa về giá giữa 2 nhóm.")
        else:
            print("Kết luận: Không có sự khác biệt ý nghĩa về giá giữa 2 nhóm.")

        fig, ax = plt.subplots(figsize=(9, 6))
        ax.hist(gia_a, bins=15, alpha=0.6, label=str(nhan_a), color='#2196F3')
        ax.hist(gia_b, bins=15, alpha=0.6, label=str(nhan_b), color='#FF5722')
        ax.set_title(f'Phân phối giá: {tieu_de}')
        ax.set_xlabel('Giá (VNĐ)')
        ax.set_ylabel('Số sản phẩm')
        ax.legend()
        fig.tight_layout()
        return fig

    def cau_4_top_san_pham_ban_chay(self):
        print("\n--- CÂU 4: TOP 5 SẢN PHẨM BÁN CHẠY NHẤT ---")
        top_sp = self.df.nlargest(5, 'luot_ban')[['ten_san_pham', 'luot_ban']]
        nhan = top_sp['ten_san_pham'].str.slice(0, 25) + '...'

        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.bar(nhan, top_sp['luot_ban'], color='#4CAF50')
        ax.set_title('Top 5 Sản phẩm có lượt bán cao nhất')
        ax.set_xlabel('Sản phẩm')
        ax.set_ylabel('Lượt bán')
        ax.tick_params(axis='x', rotation=20)
        for label in ax.get_xticklabels():
            label.set_ha('right')

        for bar in bars:
            yval = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2, yval, int(yval), va='bottom', ha='center')
        fig.tight_layout()
        return fig

    def cau_5_ti_trong_nganh_hang(self):
        print("\n--- CÂU 5: TỶ TRỌNG SẢN PHẨM THEO NGÀNH HÀNG ---")
        pie_data = self.df['nganh_hang'].value_counts().nlargest(5)
        mau_dam = ['#2E86AB', '#E27D60', '#41B3A3', '#C38D9E', '#8367C7']

        fig, ax = plt.subplots(figsize=(8, 8))
        wedges, texts, autotexts = ax.pie(
            pie_data.values, labels=pie_data.index, autopct='%1.1f%%',
            startangle=140, colors=mau_dam
        )
        for text, wedge in zip(texts, wedges):
            text.set_color(wedge.get_facecolor())
            text.set_fontweight('bold')
            text.set_fontsize(11)
        ax.set_title('Cơ cấu Top 5 Ngành hàng có nhiều sản phẩm nhất')
        return fig

    def cau_6_giam_gia_ao(self):
        """Trả về dict số liệu (không print-only) để Streamlit đưa thẳng
        vào st.metric ở Tab 1 Tổng quan."""
        if 'da_kiem_tra_gia_ao' not in self.df.columns:
            return {"co_du_lieu": False}

        so_luong = int(self.df['da_kiem_tra_gia_ao'].sum())
        tong_so = len(self.df)
        ti_le = round(so_luong / tong_so * 100, 1)
        trung_binh_giam = (self.df.groupby('da_kiem_tra_gia_ao')['ty_le_giam'].mean() * 100).round(1)

        ket_qua = {
            "co_du_lieu": True,
            "so_luong": so_luong,
            "tong_so": tong_so,
            "ti_le": ti_le,
            "giam_gia_tb_nghi_ngo": float(trung_binh_giam.get(True, 0)),
            "giam_gia_tb_binh_thuong": float(trung_binh_giam.get(False, 0)),
        }

        print("\n--- CÂU 6: NHẬN DIỆN GIẢM GIÁ ẢO (dùng cờ của A) ---")
        print(f"Số sản phẩm bị gắn cờ nghi giảm giá ảo: {so_luong}/{tong_so} ({ti_le}%)")
        print(f"% giảm giá TB nhóm nghi ngờ: {ket_qua['giam_gia_tb_nghi_ngo']}% "
              f"| nhóm bình thường: {ket_qua['giam_gia_tb_binh_thuong']}%")
        return ket_qua


# ==========================================
# 3. CHẠY THỬ (khi chạy trực tiếp file này, không phải khi import vào Streamlit)
# ==========================================
if __name__ == "__main__":
    pt_thongke = PhanTichThongKe(df_clean)
    pt_thongke.cau_1_phan_phoi_nganh_hang()
    pt_thongke.cau_2_tuong_quan_spearman()
    pt_thongke.cau_3_kiem_dinh_mann_whitney()
    pt_thongke.cau_4_top_san_pham_ban_chay()
    pt_thongke.cau_5_ti_trong_nganh_hang()
    pt_thongke.cau_6_giam_gia_ao()
    plt.show()  # hiện tất cả các figure đã tạo cùng lúc khi chạy độc lập