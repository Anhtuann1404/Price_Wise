import pandas as pd
import numpy as np
import plotly.express as px
import scipy.stats as stats

class PhanTichThongKe:
    def __init__(self, df):
        self.df = df
        self.mau_chu_dao = "#5EEAD4" # Màu xanh mòng két đồng bộ với UI

    def cau_1_phan_phoi_nganh_hang(self):
        top_nganh = self.df['nganh_hang'].value_counts().nlargest(5).index
        df_top = self.df[self.df['nganh_hang'].isin(top_nganh)]
        
        # Dùng Plotly Boxplot
        fig = px.box(
            df_top, x="nganh_hang", y="gia", color="nganh_hang",
            title="Phân phối giá theo Top 5 Ngành hàng (Thực tế)",
            labels={"nganh_hang": "Ngành hàng", "gia": "Giá (VNĐ)"}
        )
        return fig

    def cau_2_tuong_quan_spearman(self):
        corr, _ = stats.spearmanr(self.df['ty_le_giam'], self.df['luot_ban'])
        df_plot = self.df.copy()
        df_plot['ty_le_giam_pt'] = df_plot['ty_le_giam'] * 100
        
        # Dùng Plotly Scatter có thang màu (color scale)
        fig = px.scatter(
            df_plot, x="ty_le_giam_pt", y="luot_ban", color="danh_gia",
            hover_data=["ten_san_pham", "shop"],
            title=f"Tương quan Giảm giá & Lượt bán (Spearman: {corr:.2f})",
            labels={"ty_le_giam_pt": "Giảm giá (%)", "luot_ban": "Lượt bán", "danh_gia": "Đánh giá"},
            color_continuous_scale="Tealgrn"
        )
        return fig

    def cau_3_kiem_dinh_mann_whitney(self):
        top2_nganh = self.df['nganh_hang'].value_counts().nlargest(2)
        df_plot = pd.DataFrame()
        tieu_de = ""

        # Logic fallback đảm bảo biểu đồ luôn chạy
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

        # Dùng Plotly Histogram chồng lớp (overlay)
        fig = px.histogram(
            df_plot, x="gia", color="Nhom", barmode="overlay",
            title=f"Phân phối giá: {tieu_de}",
            labels={"gia": "Giá (VNĐ)", "Nhom": "Nhóm"}
        )
        fig.update_traces(opacity=0.7) # Làm biểu đồ trong suốt để dễ nhìn lớp dưới
        return fig

    def cau_4_top_san_pham_ban_chay(self):
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
        pie_data = self.df['nganh_hang'].value_counts().nlargest(5).reset_index()
        pie_data.columns = ['nganh_hang', 'count']
        
        # Đổi thành biểu đồ Donut (có lỗ ở giữa) trông hiện đại hơn
        fig = px.pie(
            pie_data, names="nganh_hang", values="count",
            title="Cơ cấu Top 5 Ngành hàng",
            hole=0.4 
        )
        fig.update_traces(textposition='inside', textinfo='percent+label')
        return fig

    def cau_6_giam_gia_ao(self):
        if 'da_kiem_tra_gia_ao' not in self.df.columns:
            return {"co_du_lieu": False}
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