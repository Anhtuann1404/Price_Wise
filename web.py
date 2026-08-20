"""
PriceWise - Trợ lý phân tích giá & mua sắm thông minh cho sản phẩm TMĐT.
Tích hợp end-to-end: Data Engineering (A) -> Data Analysis (B) -> Machine Learning (C) -> Dashboard (D)
"""

import pandas as pd
import plotly.express as px
import streamlit as st
import sqlite3 
import time
from src.link_preview import lay_thong_tin_link

# Import các Class OOP từ thư mục src/
from src.data_analysis import PhanTichThongKe
from src.machine_learning import PhanTichGia, TroLyMuaSam

# Thiết lập cấu hình trang
st.set_page_config(
    page_title="PriceWise - DT03",
    page_icon="🛒",
    layout="wide",
)

# ======================================================================
# CẤU HÌNH GIAO DIỆN (CSS)
# ======================================================================
MAU_CUM = {
    "Hời / đáng cân nhắc": "#34D399",
    "Tầm trung / ổn": "#FBBF24",
    "Đắt / chưa xứng giá": "#F87171",
}
MAU_NEN_BIEU_DO = "#5EEAD4"

CSS_TUY_CHINH = """
<style>
.pw-banner {
    background: linear-gradient(120deg, #10141C 0%, #1B2A4A 55%, #16413E 100%);
    padding: 26px 32px;
    border-radius: 16px;
    border-bottom: 3px solid #5EEAD4;
    color: #E5E7EB;
    margin-bottom: 22px;
}
.pw-banner h1 { margin: 0; font-size: 28px; color: #F1F5F9; }
.pw-banner p { margin: 6px 0 0 0; color: #A9B7CC; font-size: 15px; }

div[data-testid="stMetric"] {
    background-color: #171B22;
    border: 1px solid #262B33;
    border-left: 3px solid #5EEAD4;
    border-radius: 14px;
    padding: 14px 16px;
}

/* NÂNG CẤP 1: CSS CHUẨN UX CHO THẺ SẢN PHẨM & HIỆU ỨNG HOVER */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #171B22;
    border: 1px solid #262B33 !important;
    border-radius: 16px !important;
    padding: 4px 6px;
    transition: all 0.3s ease; /* Chuyển động mượt mà khi di chuột */
}

/* Khi chuột lướt qua: Đẩy thẻ lên 4px, phát sáng viền và đổ bóng */
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    transform: translateY(-4px);
    border-color: #5EEAD4 !important;
    box-shadow: 0 8px 24px rgba(94, 234, 212, 0.15);
}

.pw-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    margin-right: 6px;
}
.pw-badge-hoi { background: rgba(52,211,153,0.15); color:#34D399; }
.pw-badge-tam { background: rgba(251,191,36,0.15); color:#FBBF24; }
.pw-badge-dat { background: rgba(248,113,113,0.15); color:#F87171; }

.pw-card-title { 
    font-size: 16px; 
    font-weight: 700; 
    color:#E5E7EB; 
    margin-bottom: 6px;
    /* Ép tiêu đề luôn cao 48px và tối đa 2 dòng */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    height: 48px;
}
.pw-card-price { color:#5EEAD4; font-weight:700; font-size: 15px; }

.pw-reasoning-box {
    background-color: rgba(94, 234, 212, 0.08); 
    padding: 10px 14px; 
    border-radius: 8px; 
    margin: 12px 0; 
    font-size: 14.5px; 
    border-left: 4px solid #5EEAD4;
    color: #E5E7EB;
    /* Ép khung giải thích luôn cao 110px và tối đa 4 dòng */
    height: 110px;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
</style>
"""

def hien_banner():
    st.markdown(CSS_TUY_CHINH, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="pw-banner">
            <h1>🛒 PriceWise</h1>
            <p>Hệ thống Phân tích giá & Trợ lý mua sắm thông minh · Đề tài DT03</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

def nhan_phan_khuc(ten_nhom: str) -> str:
    lop = {
        "Hời / đáng cân nhắc": "pw-badge-hoi",
        "Tầm trung / ổn": "pw-badge-tam",
        "Đắt / chưa xứng giá": "pw-badge-dat",
    }.get(ten_nhom, "pw-badge-tam")
    return f'<span class="pw-badge {lop}">{ten_nhom}</span>'

def bieu_do_dep(fig):
    fig.update_layout(
        template="plotly_dark",
        font_family="sans-serif",
        font_color="#CBD5E1",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    fig.update_xaxes(gridcolor="#2A2F3A", zerolinecolor="#2A2F3A")
    fig.update_yaxes(gridcolor="#2A2F3A", zerolinecolor="#2A2F3A")
    return fig


# ======================================================================
# CACHE & PIPELINE XỬ LÝ (TỐI ƯU HIỆU NĂNG)
# ======================================================================
@st.cache_data
def doc_du_lieu():
    """Đọc dữ liệu sạch từ cơ sở dữ liệu SQLite."""
    conn = sqlite3.connect("data/pricewise_database.db")
    df = pd.read_sql_query("SELECT * FROM san_pham", conn)
    conn.close()
    return df

@st.cache_resource
def chay_pipeline_hoc_may(df):
    """Khởi tạo và chạy pipeline thống kê & học máy."""
    # 1. Thống kê (Của B)
    pt_thong_ke = PhanTichThongKe(df)
    
    # 2. Học Máy (Của C)
    pt_gia = PhanTichGia(df)
    pt_gia.tinh_value_score()
    pt_gia.phan_cum_kmeans()  # Tự động chọn k tối ưu
    
    df_ml = pt_gia.df  # DF đã có value_score và cụm
    tro_ly = TroLyMuaSam(df_ml)
    
    return df_ml, pt_thong_ke, pt_gia, tro_ly


# ======================================================================
# MAIN APP
# ======================================================================
def main():
    hien_banner()

    try:
        df_goc = doc_du_lieu()
        df_ml, pt_thong_ke, pt_gia, tro_ly = chay_pipeline_hoc_may(df_goc)
    except Exception as e:
        st.error(f"Lỗi khởi tạo hệ thống: Đảm bảo file 'data/pricewise_database.db' và thư mục 'src/' tồn tại. Chi tiết lỗi: {e}")
        return

    tab_tong_quan, tab_phan_khuc, tab_tro_ly = st.tabs(
        ["📊 Tổng quan & Thống kê", "🧩 Phân Khúc Sản Phẩm", "🛍️ Trợ lý mua sắm AI"]
    )

    danh_sach_nganh = df_ml['nganh_hang'].unique().tolist()

    so_luong_theo_nganh = df_ml['nganh_hang'].value_counts()
    NGUONG_TOI_THIEU = 3
    nganh_du_du_lieu = [n for n in danh_sach_nganh if so_luong_theo_nganh[n] >= NGUONG_TOI_THIEU]

    # ------------------------------------------------------------------
    # TAB 1: TỔNG QUAN & THỐNG KÊ 
    # ------------------------------------------------------------------
    with tab_tong_quan:
        st.markdown("### 1. Bộ lọc Dữ liệu")
        cot_loc1, cot_loc2 = st.columns(2)
        with cot_loc1:
            nganh_chon = st.multiselect("Ngành hàng", options=danh_sach_nganh, default=danh_sach_nganh)
        with cot_loc2:
            khoang_gia = st.slider(
                "Khoảng giá (VNĐ)",
                min_value=int(df_ml["gia"].min()), max_value=int(df_ml["gia"].max()),
                value=(int(df_ml["gia"].min()), int(df_ml["gia"].max())), step=10_000,
            )

        df_loc = df_ml[df_ml["nganh_hang"].isin(nganh_chon) & df_ml["gia"].between(*khoang_gia)]

        # --- KPIs ---
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Số sản phẩm", f"{len(df_loc):,}")
        kpi2.metric("Giá trung bình", f"{df_loc['gia'].mean():,.0f} đ" if not df_loc.empty else "—")
        kpi3.metric("Đánh giá trung bình", f"{df_loc['danh_gia'].mean():.2f} ⭐" if not df_loc.empty else "—")
        
        kq_gia_ao = pt_thong_ke.cau_6_giam_gia_ao()
        if kq_gia_ao and kq_gia_ao["co_du_lieu"]:
            kpi4.metric("Sản phẩm nghi giảm giá ảo", f"{kq_gia_ao['so_luong']} ({kq_gia_ao['ti_le']}%)")
        else:
            kpi4.metric("Giảm giá trung bình", f"{df_loc['ty_le_giam'].mean() * 100:.1f}%" if not df_loc.empty else "—")

        # --- Bảng điều khiển phân tích thống kê ---
        st.markdown("---")
        st.markdown("### 2. Phân tích Thống kê Chuyên sâu")
        
        col_a, col_b = st.columns(2)
        with col_a:
            with st.container(border=True):
                st.plotly_chart(bieu_do_dep(px.histogram(df_loc, x="gia", title="Phân phối giá toàn tập", color_discrete_sequence=[MAU_NEN_BIEU_DO])), use_container_width=True)
            with st.container(border=True):
                st.pyplot(pt_thong_ke.cau_3_kiem_dinh_mann_whitney())
            with st.container(border=True):
                st.plotly_chart(bieu_do_dep(pt_thong_ke.cau_5_ti_trong_nganh_hang()), use_container_width=True)

        with col_b:
            with st.container(border=True):
                st.pyplot(pt_thong_ke.cau_1_phan_phoi_nganh_hang())
            with st.container(border=True):
                st.plotly_chart(bieu_do_dep(pt_thong_ke.cau_2_tuong_quan_spearman()), use_container_width=True)
            with st.container(border=True):
                st.plotly_chart(bieu_do_dep(pt_thong_ke.cau_4_top_san_pham_ban_chay()), use_container_width=True)

    # ------------------------------------------------------------------
    # TAB 2: PHÂN KHÚC GIÁ 
    # ------------------------------------------------------------------
    with tab_phan_khuc:
        st.markdown("### Mô hình Phân khúc Sản phẩm (K-Means Clustering)")
        
        col_cluster1, col_cluster2 = st.columns([2, 1])
        with col_cluster1:
            with st.container(border=True):
                fig_cluster = px.scatter(
                    df_ml, x="gia", y="value_score", color="ten_cum",
                    hover_data=["ten_san_pham", "danh_gia", "ty_le_giam"],
                    title="Bản đồ Phân khúc Sản phẩm (Trục Giá vs Trục Giá trị)",
                )
                st.plotly_chart(bieu_do_dep(fig_cluster), use_container_width=True)
                
        with col_cluster2:
            with st.container(border=True):
                st.markdown("**Kiểm định K tối ưu (Silhouette & Elbow)**")
                bang_k = pt_gia.bang_chon_k
                st.dataframe(bang_k.style.highlight_max(subset=['silhouette'], color='#16413E'), hide_index=True, use_container_width=True)

        st.markdown("### Chân dung các phân khúc")
        df_mota = pt_gia.bao_cao_chan_dung_cum()
        
        cot_cum = st.columns(len(df_mota))
        for cot, (_, hang) in zip(cot_cum, df_mota.iterrows()):
            with cot:
                with st.container(border=True):
                    ten_tach = hang['ten_cum'].split(' - ')
                    huy_hieu = ten_tach[1] if len(ten_tach) > 1 else hang['ten_cum']
                    
                    st.markdown(nhan_phan_khuc(huy_hieu), unsafe_allow_html=True)
                    st.metric("Số lượng SP", f"{hang['so_sp']:,.0f}")
                    st.caption(
                        f"**Giá TB:** {hang['gia_tb']:,.0f} đ<br>"
                        f"**Rating TB:** {hang['rating_tb']:.1f} ⭐<br>"
                        f"**Điểm giá trị:** {hang['value_score_tb']:.1f}", unsafe_allow_html=True
                    )
                    st.info(hang['mo_ta'])

    # ------------------------------------------------------------------
    # TAB 3: TRỢ LÝ MUA SẮM AI 
    # ------------------------------------------------------------------
    with tab_tro_ly:
        st.markdown("### 🤖 Trợ lý phân tích & Gợi ý sản phẩm thông minh")
        col_input1, col_input2 = st.columns(2)
        with col_input1:
            nhan_nganh = {
                f"{n} ({so_luong_theo_nganh[n]} sản phẩm)": n for n in nganh_du_du_lieu
            }
            lua_chon_hien_thi = st.selectbox("Ngành hàng bạn quan tâm:", list(nhan_nganh.keys()))
            nganh_hang_tu_van = nhan_nganh[lua_chon_hien_thi]
        with col_input2:
            ngan_sach_tu_van = st.number_input(
                "Ngân sách dự kiến (VNĐ):", min_value=10_000, max_value=100_000_000,
                value=200_000, step=50_000,
            )

        if st.button("Tư vấn ngay", type="primary", use_container_width=True):
            goi_y = tro_ly.goi_y_theo_ngan_sach(ngan_sach_tu_van, nganh_hang_tu_van, top_n=3)

            if goi_y.empty:
                # NÂNG CẤP 2: Dùng toast thay cho st.warning nếu không tìm thấy
                st.toast(f"Hơi tiếc! Không có sản phẩm nào hợp với {ngan_sach_tu_van:,.0f} đ.", icon="🤔")
            else:
                # NÂNG CẤP 2: Dùng toast xịn xò bật lên ở góc dưới màn hình
                st.toast(f"Ting ting! Đã tìm thấy {len(goi_y)} sản phẩm tối ưu!", icon="🎉")
                
                tb_rating = df_ml[df_ml['nganh_hang'] == nganh_hang_tu_van]['danh_gia'].mean()
                tb_luot_ban = df_ml[df_ml['nganh_hang'] == nganh_hang_tu_van]['luot_ban'].mean()

                cot_goi_y = st.columns(len(goi_y))
                for idx, (_, sp) in enumerate(goi_y.iterrows()):
                    with cot_goi_y[idx]:
                        with st.container(border=True):
                            preview = lay_thong_tin_link(sp["url"])
                            if preview and preview["image"]:
                                st.markdown(
                                    f'<img src="{preview["image"]}" style="width: 100%; height: auto; border-radius: 8px; margin-bottom: 10px;">',
                                    unsafe_allow_html=True
                                )
                            else:
                                st.markdown(
                                    '<div style="width: 100%; aspect-ratio: 1/1; background-color: #262B33; border-radius: 8px; margin-bottom: 10px; display: flex; align-items: center; justify-content: center; color: #A9B7CC;">Không có ảnh</div>', 
                                    unsafe_allow_html=True
                                )
                            
                            st.markdown(f'<div class="pw-card-title">{sp["ten_san_pham"]}</div>', unsafe_allow_html=True)
                            
                            nhan_badge = sp["ten_cum"].split(' - ')[1] if ' - ' in sp["ten_cum"] else sp["ten_cum"]
                            
                            st.markdown(
                                f'<span class="pw-card-price">{sp["gia"]:,.0f} đ</span> '
                                f'{nhan_phan_khuc(nhan_badge)}',
                                unsafe_allow_html=True,
                            )
                            
                            pct_re_hon = (1 - sp["gia"] / ngan_sach_tu_van) * 100
                            ly_do = f"💡 Rẻ hơn ngân sách {pct_re_hon:.0f}%"
                            
                            if sp['danh_gia'] > tb_rating:
                                ly_do += f", đánh giá cao vượt trội ({sp['danh_gia']} ⭐ so với TB {tb_rating:.1f})"
                            elif sp['danh_gia'] >= 4.0:
                                ly_do += f", mức đánh giá an toàn ({sp['danh_gia']} ⭐)"
                                
                            if sp['luot_ban'] > tb_luot_ban:
                                ly_do += f", và thuộc top bán chạy ({sp['luot_ban']} lượt)."
                            else:
                                ly_do += "."

                            st.markdown(f'<div class="pw-reasoning-box">{ly_do}</div>', unsafe_allow_html=True)
                            
                            st.caption(f"**Value Score:** {sp['value_score']:.1f}/100")
                            st.markdown(f"[🔗 Xem chi tiết sản phẩm trên sàn]({sp['url']})")

if __name__ == "__main__":
    main()