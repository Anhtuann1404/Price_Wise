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
# để khớp 100% với schema đang dùng trong streamlit_app.py của D/C, không đổi
# tên/ánh xạ gì thêm ở đây nữa.
thu_muc_hien_tai = os.path.dirname(os.path.abspath(__file__))
duong_dan_file = os.path.join(thu_muc_hien_tai, '..', 'data', 'dulieu_sach_v3.csv')
df = pd.read_csv(duong_dan_file)
df_clean = df.copy()

print("Đang xử lý làm sạch dữ liệu...")
print(f"Số sản phẩm: {len(df_clean)} | Số ngành hàng: {df_clean['nganh_hang'].nunique()}")

# Lưu ý: ty_le_giam trong data gốc là số thập phân 0-1 (0.09, 0.39...), KHÔNG
# đổi sang thang %-100 nữa để tránh lệch với cách streamlit_app.py đang dùng
# (df_loc['ty_le_giam'].mean() * 100 khi hiển thị KPI). Muốn hiển thị % chỉ
# cần nhân 100 ngay tại chỗ in/vẽ, không lưu thành cột riêng.

# Fake tạm 2 cột của Thành viên C (ML) để code không bị lỗi khi chạy trước
# TODO: xóa 2 dòng dưới khi C bàn giao value_score / cum_kmeans thật.
df_clean['value_score'] = np.random.uniform(50, 100, len(df_clean))
df_clean['cum_kmeans'] = np.random.choice(['Giá rẻ', 'Tầm trung', 'Cao cấp'], len(df_clean))

# ==========================================
# 3. CLASS PHÂN TÍCH THỐNG KÊ
# ==========================================
# Đổi tên từ PhanTichGia -> PhanTichThongKe để không đụng tên với class
# PhanTichGia bên demo.py/streamlit_app.py (C viết, chuyên tính value_score
# + KMeans) - 2 class nội dung khác hẳn nhau, giữ trùng tên sẽ đè lẫn nhau
# khi import chung vào app.
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

        plt.figure(figsize=(10, 6))
        top_nganh = self.df['nganh_hang'].value_counts().nlargest(5).index
        df_top = self.df[self.df['nganh_hang'].isin(top_nganh)]

        groups = [df_top[df_top['nganh_hang'] == nganh]['gia'] for nganh in top_nganh]
        plt.boxplot(groups, tick_labels=top_nganh, patch_artist=True)
        plt.title('Phân phối giá theo Top 5 Ngành hàng (Thực tế)')
        plt.ylabel('Giá (VNĐ)')
        plt.xticks(rotation=15)
        plt.tight_layout()
        plt.show()

    def cau_2_tuong_quan_spearman(self):
        print("\n--- CÂU 2: TƯƠNG QUAN ---")
        corr, p_value = stats.spearmanr(self.df['ty_le_giam'], self.df['luot_ban'])
        print(f"Spearman (% Giảm giá & Lượt bán): {corr:.3f}, P-value: {p_value:.3e}")

        plt.figure(figsize=(9, 6))
        scatter = plt.scatter(self.df['ty_le_giam'] * 100, self.df['luot_ban'],
                              c=self.df['danh_gia'], cmap='viridis', alpha=0.6)
        plt.title('Tương quan % Giảm giá và Lượt bán (Dữ liệu Tiki)')
        plt.xlabel('Phần trăm giảm giá (%)')
        plt.ylabel('Lượt bán')
        plt.colorbar(scatter).set_label('Điểm đánh giá')
        plt.show()

    def cau_3_kiem_dinh_mann_whitney(self):
        print("\n--- CÂU 3: KIỂM ĐỊNH MANN-WHITNEY U ---")
        # Chia sản phẩm thành 2 nhóm: Giảm giá sâu (>20%) và Giảm giá ít/Không giảm (<=20%)
        # ty_le_giam là số thập phân 0-1 -> ngưỡng 20% viết là 0.2
        nhom_cao = self.df[self.df['ty_le_giam'] > 0.2]['luot_ban']
        nhom_thap = self.df[self.df['ty_le_giam'] <= 0.2]['luot_ban']

        stat, p_value = stats.mannwhitneyu(nhom_cao, nhom_thap, alternative='two-sided')
        print(f"Chỉ số U: {stat:.2f}, P-value: {p_value:.4f}")
        if p_value < 0.05:
            print("Kết luận: Có sự khác biệt ý nghĩa về lượt bán giữa 2 nhóm giảm giá.")
        else:
            print("Kết luận: Không có sự khác biệt ý nghĩa về lượt bán.")

        plt.figure(figsize=(9, 6))
        plt.hist(nhom_thap, bins=15, alpha=0.6, label='Giảm giá <= 20%', color='#2196F3')
        plt.hist(nhom_cao, bins=15, alpha=0.6, label='Giảm giá > 20%', color='#FF5722')
        plt.title('Phân phối lượt bán theo nhóm mức giảm giá')
        plt.xlabel('Lượt bán')
        plt.ylabel('Số sản phẩm')
        plt.legend()
        plt.tight_layout()
        plt.show()

    def cau_4_top_san_pham_ban_chay(self):
        print("\n--- CÂU 4: TOP 5 SẢN PHẨM BÁN CHẠY NHẤT ---")
        top_sp = self.df.nlargest(5, 'luot_ban')[['ten_san_pham', 'luot_ban']]
        nhan = top_sp['ten_san_pham'].str.slice(0, 25) + '...'

        plt.figure(figsize=(10, 6))
        bars = plt.bar(nhan, top_sp['luot_ban'], color='#4CAF50')
        plt.title('Top 5 Sản phẩm có lượt bán cao nhất')
        plt.xlabel('Sản phẩm')
        plt.ylabel('Lượt bán')
        plt.xticks(rotation=20, ha='right')

        for bar in bars:
            yval = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2, yval, int(yval), va='bottom', ha='center')
        plt.tight_layout()
        plt.show()

    def cau_5_ti_trong_nganh_hang(self):
        print("\n--- CÂU 5: TỶ TRỌNG SẢN PHẨM THEO NGÀNH HÀNG ---")
        pie_data = self.df['nganh_hang'].value_counts().nlargest(5)

        plt.figure(figsize=(8, 8))
        mau_dam = ['#2E86AB', '#E27D60', '#41B3A3', '#C38D9E', '#8367C7']
        wedges, texts, autotexts = plt.pie(
            pie_data.values, labels=pie_data.index, autopct='%1.1f%%',
            startangle=140, colors=mau_dam
        )
        for text, wedge in zip(texts, wedges):
            text.set_color(wedge.get_facecolor())
            text.set_fontweight('bold')
            text.set_fontsize(11)
        plt.title('Cơ cấu Top 5 Ngành hàng có nhiều sản phẩm nhất')
        plt.show()

    def cau_6_giam_gia_ao(self):
        print("\n--- CÂU 6: NHẬN DIỆN GIẢM GIÁ ẢO (dùng cờ của A) ---")
        if 'da_kiem_tra_gia_ao' not in self.df.columns:
            print("Không tìm thấy cột 'da_kiem_tra_gia_ao', bỏ qua câu này.")
            return

        so_luong = self.df['da_kiem_tra_gia_ao'].sum()
        ti_le = so_luong / len(self.df) * 100
        print(f"Số sản phẩm bị gắn cờ nghi giảm giá ảo: {so_luong} ({ti_le:.1f}%)")

        trung_binh_giam = self.df.groupby('da_kiem_tra_gia_ao')['ty_le_giam'].mean() * 100
        print("% giảm giá trung bình theo nhóm bị gắn cờ hay không:")
        print(trung_binh_giam)

    def chay_tat_ca(self):
        self.cau_1_phan_phoi_nganh_hang()
        self.cau_2_tuong_quan_spearman()
        self.cau_3_kiem_dinh_mann_whitney()
        self.cau_4_top_san_pham_ban_chay()
        self.cau_5_ti_trong_nganh_hang()
        self.cau_6_giam_gia_ao()


# ==========================================
# 4. CHẠY THỬ
# ==========================================
if __name__ == "__main__":
    pt_thongke = PhanTichThongKe(df_clean)
    pt_thongke.chay_tat_ca()