import pandas as pd
import numpy as np
import plotly.express as px
import scipy.stats as stats
import matplotlib.pyplot as plt
import seaborn as sns

class PhanTichThongKe:
    """
    Lớp thực hiện các phân tích thống kê mô tả và kiểm định trên dữ liệu.
    Kết hợp linh hoạt giữa Matplotlib/Seaborn và Plotly.
    Đã được tối ưu giao diện Dark Mode để đồng bộ hoàn hảo với Streamlit.
    """
    def __init__(self, df):
        self.df = df
        self.mau_chu_dao = "#5EEAD4" # Màu xanh mòng két
        
        # Cài đặt giao diện TỐI cho Matplotlib/Seaborn
        plt.style.use('dark_background')
        sns.set_theme(
            style="darkgrid", 
            rc={
                "axes.facecolor": "#0E1117",     # Mã màu nền chuẩn của Streamlit
                "figure.facecolor": "#0E1117",   # Nền viền bên ngoài
                "text.color": "white",
                "axes.labelcolor": "white",
                "xtick.color": "white",
                "ytick.color": "white",
                "grid.color": "#333333",         # Lưới mờ
                "axes.edgecolor": "#555555"
            }
        )

    def cau_1_phan_phoi_nganh_hang(self):
        """
        Câu 1 (Dùng Seaborn/Matplotlib): Phân phối giá theo Top 5 Ngành hàng.
        """
        top_nganh = self.df['nganh_hang'].value_counts().nlargest(5).index
        df_top = self.df[self.df['nganh_hang'].isin(top_nganh)]
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Dùng danh sách màu tối ưu Dark Mode (Bao gồm màu chủ đạo)
        bang_mau = [self.mau_chu_dao, "#38BDF8", "#F472B6", "#A78BFA", "#FBBF24"]
        sns.boxplot(data=df_top, x="nganh_hang", y="gia", hue="nganh_hang", palette=bang_mau, legend=False, ax=ax)
        
        ax.set_title("Phân phối giá theo Top 5 Ngành hàng (Thực tế)", fontsize=14, fontweight='bold')
        ax.set_xlabel("Ngành hàng", fontsize=12)
        ax.set_ylabel("Giá (VNĐ)", fontsize=12)
        plt.tight_layout()
        
        plt.close(fig) 
        return fig

    def cau_2_tuong_quan_spearman(self):
        """
        Câu 2 (Dùng Plotly): Tương quan giữa giảm giá và lượt bán.
        """
        corr, _ = stats.spearmanr(self.df['ty_le_giam'], self.df['luot_ban'])
        df_plot = self.df.copy()
        df_plot['ty_le_giam_pt'] = df_plot['ty_le_giam'] * 100
        
        fig = px.scatter(
            df_plot, x="ty_le_giam_pt", y="luot_ban", color="danh_gia",
            hover_data=["ten_san_pham", "shop"],
            title=f"Tương quan Giảm giá & Lượt bán (Spearman: {corr:.2f})",
            labels={"ty_le_giam_pt": "Giảm giá (%)", "luot_ban": "Lượt bán", "danh_gia": "Đánh giá"},
            color_continuous_scale="Tealgrn"
        )
        return fig

    def cau_3_kiem_dinh_mann_whitney(self):
        """
        Câu 3 (Dùng Seaborn/Matplotlib): Kiểm định sự khác biệt về giá.
        """
        top2_nganh = self.df['nganh_hang'].value_counts().nlargest(2)
        df_plot = pd.DataFrame()
        tieu_de = ""

        if len(top2_nganh) >= 2:
            nhan_a, nhan_b = top2_nganh.index[0], top2_nganh.index[1]
            df_plot = self.df[self.df['nganh_hang'].isin([nhan_a, nhan_b])].copy()
            df_plot['Nhom'] = df_plot['nganh_hang']
            tieu_de = f"Ngành hàng: {nhan_a} vs {nhan_b}"
        else:
            top2_shop = self.df['shop'].value_counts().nlargest(2)
            if len(top2_shop) >= 2:
                nhan_a, nhan_b = top2_shop.index[0], top2_shop.index[1]
                df_plot = self.df[self.df['shop'].isin([nhan_a, nhan_b])].copy()
                df_plot['Nhom'] = df_plot['shop']
                tieu_de = f"Shop: {nhan_a} vs {nhan_b}"
            else:
                df_plot = self.df.copy()
                df_plot['Nhom'] = np.where(df_plot['ty_le_giam'] > 0.2, "Giảm > 20%", "Giảm <= 20%")
                tieu_de = "Mức giảm giá (>20% vs <=20%)"

        nhom_ten = df_plot['Nhom'].unique()
        gia_a = df_plot[df_plot['Nhom'] == nhom_ten[0]]['gia']
        gia_b = df_plot[df_plot['Nhom'] == nhom_ten[1]]['gia']
        stat, p_value = stats.mannwhitneyu(gia_a, gia_b, alternative='two-sided')
        ket_luan = "Có khác biệt ý nghĩa" if p_value < 0.05 else "Không khác biệt ý nghĩa"

        fig, ax = plt.subplots(figsize=(10, 6))
        
        # Dùng màu chủ đạo và một màu cam tương phản cho 2 nhóm
        bang_mau = [self.mau_chu_dao, "#FBBF24"]
        sns.histplot(data=df_plot, x="gia", hue="Nhom", palette=bang_mau, kde=True, element="step", stat="density", common_norm=False, ax=ax)
        
        ax.set_title(f"Phân phối giá: {tieu_de}\n(Mann-Whitney U={stat:.1f}, p={p_value:.4f} → {ket_luan})", fontsize=13, fontweight='bold')
        ax.set_xlabel("Giá (VNĐ)", fontsize=12)
        ax.set_ylabel("Mật độ phân phối", fontsize=12)
        plt.tight_layout()
        
        plt.close(fig) 
        return fig

    def cau_4_top_san_pham_ban_chay(self):
        """
        Câu 4 (Dùng Plotly): Top 5 sản phẩm bán chạy.
        """
        top_sp = self.df.nlargest(5, 'luot_ban').copy()
        top_sp['nhan'] = top_sp['ten_san_pham'].str.slice(0, 30) + '...'
        
        fig = px.bar(
            top_sp, x="nhan", y="luot_ban",
            title="Top 5 Sản phẩm bán chạy nhất",
            labels={"nhan": "Sản phẩm", "luot_ban": "Lượt bán"},
            text="luot_ban",
            color_discrete_sequence=[self.mau_chu_dao]
        )
        return fig

    def cau_5_ti_trong_nganh_hang(self):
        """
        Câu 5 (Dùng Plotly): Cơ cấu sản phẩm.
        """
        pie_data = self.df['nganh_hang'].value_counts().nlargest(5).reset_index()
        pie_data.columns = ['nganh_hang', 'count']
        
        fig = px.pie(
            pie_data, names="nganh_hang", values="count",
            title="Cơ cấu Top 5 Ngành hàng",
            hole=0.4 
        )
        fig.update_traces(textposition='inside', textinfo='percent+label')
        return fig

    def cau_6_giam_gia_ao(self):
        """Trả về dữ liệu tính toán cho giao diện."""
        if 'da_kiem_tra_gia_ao' not in self.df.columns:
            return {"co_du_lieu": False}
        self.df['da_kiem_tra_gia_ao'] = self.df['da_kiem_tra_gia_ao'].astype(bool)
        so_luong = int(self.df['da_kiem_tra_gia_ao'].sum())
        tong_so = len(self.df)
        ti_le = round(so_luong / tong_so * 100, 1)
        trung_binh_giam = (self.df.groupby('da_kiem_tra_gia_ao')['ty_le_giam'].mean() * 100).round(1)
        
        return {
            "co_du_lieu": True,
            "so_luong": so_luong,
            "tong_so": tong_so,
            "ti_le": ti_le,
            "giam_gia_tb_nghi_ngo": float(trung_binh_giam.get(True, 0)),
            "giam_gia_tb_binh_thuong": float(trung_binh_giam.get(False, 0)),
        }