# PriceWise - Hướng dẫn Thành viên A (Data Engineer)

## 📋 Mục đích

**PriceWise** là hệ thống phân tích giá sản phẩm TMĐT (Tiki/Shopee) kèm "trợ lý mua sắm" thông minh.

**Vai trò Thành viên A:**
- 📊 Thu thập dữ liệu từ API Tiki
- 🧹 Làm sạch & chuẩn hóa dữ liệu
- 📁 Lưu trữ với 2+ định dạng (CSV, JSON)
- 📝 Viết tài liệu & hướng dẫn

---

## 🚀 Cài đặt

### 1. Clone repo / Setup môi trường
```bash
# Tạo virtual environment
python -m venv venv

# Kích hoạt (Windows)
venv\Scripts\activate

# Kích hoạt (Linux/Mac)
source venv/bin/activate

# Cài đặt dependencies
pip install -r requirements.txt
```

### 2. Cấu trúc thư mục
```
pricewise/
├── requirements.txt                 # Thư viện cần thiết
├── thu_thap_du_lieu.py             # Module chính (Thành viên A)
├── dulieu_nhasach_tiki.csv         # Dữ liệu thô (CSV)
├── dulieu_nhasach_tiki.json        # Dữ liệu thô (JSON)
├── dulieu_nhasach_tiki_sach.csv    # Dữ liệu đã chuẩn hóa (output)
├── ngoai_lai.csv                   # Sản phẩm ngoại lai (output)
├── bao_cao_chat_luong.txt          # Báo cáo chất lượng (output)
└── README_THANH_VIEN_A.md          # File này
```

---

## 💻 Hướng dẫn Sử dụng

### A. Thu thập dữ liệu từ API Tiki

#### Cách 1: Gọi API trực tiếp (nếu server Tiki hoạt động)

```python
from thu_thap_du_lieu import ThuThapDuLieu

# Khởi tạo
bot = ThuThapDuLieu()

# Gọi API Tiki - Nhà sách (mã ngành 8322)
success = bot.goi_api_tiki(
    ma_nganh_hang="8322",  # Mã ngành hàng Tiki
    so_trang=2,             # Số trang (mỗi trang ~40 sản phẩm)
    delay=2.0               # Thời gian chờ giữa request (giây)
)

if success:
    # Lưu dữ liệu thô
    bot.luu_du_lieu("dulieu_nhasach_tiki")
    print(f"✓ Thu thập được {len(bot.du_lieu_tho)} sản phẩm")
else:
    print("❌ Gặp lỗi khi gọi API")
```

#### Cách 2: Đọc từ file CSV/JSON hiện có

```python
from thu_thap_du_lieu import ThuThapDuLieu

bot = ThuThapDuLieu()

# Đọc CSV
bot.doc_csv("dulieu_nhasach_tiki.csv")

# Hoặc đọc JSON
bot.doc_json("dulieu_nhasach_tiki.json")

print(f"✓ Đọc được {len(bot.du_lieu_tho)} sản phẩm")
```

**Mã ngành hàng Tiki:**
- 8322: Nhà sách Tiki
- 316: Thời trang nam
- 11: Điện thoại
- 7: Máy tính (xem thêm trên Tiki URL)

---

### B. Làm sạch & Chuẩn hóa Dữ liệu

```python
from thu_thap_du_lieu import ThuThapDuLieu, LamSachDuLieu

# Bước 1: Thu thập (hoặc đọc file)
bot = ThuThapDuLieu()
bot.doc_csv("dulieu_nhasach_tiki.csv")

# Bước 2: Làm sạch (một lệnh tự động chạy hết quy trình)
lam_sach = LamSachDuLieu(bot.du_lieu_tho)
df_sach = lam_sach.lay_du_lieu_sach()

# Kết quả: dữ liệu đã chuẩn hóa
print(df_sach.head())
print(f"Cột: {list(df_sach.columns)}")
```

**Quy trình Làm sạch:**

1. **Ánh xạ cột** (Tiki → PriceWise schema)
   - `id` → `ma_san_pham`
   - `name` → `ten_san_pham`
   - `price` → `gia`
   - `original_price` → `gia_goc`
   - `quantity_sold` → `luot_ban`
   - `rating_average` → `danh_gia`
   - ... (9-10 cột chính)

2. **Xử lý thiếu/trùng** (NULL, duplicates)
   - Xóa dòng có NULL ở cột bắt buộc
   - Điền mặc định cho cột phụ (shop="Tiki", nganh_hang="Chưa phân loại")
   - Xóa dòng trùng (dựa trên `ma_san_pham`)

3. **Ép kiểu dữ liệu**
   - `gia, gia_goc, ty_le_giam, luot_ban, danh_gia` → numeric
   - `nganh_hang, shop` → categorical
   - `danh_gia` giới hạn [0, 5], `ty_le_giam` giới hạn [0, 1]

4. **Phát hiện ngoại lai** (IQR + Z-score)
   - IQR: Q1 - 1.5×IQR → Q3 + 1.5×IQR
   - Z-score: |z| > 3.0
   - **Gắn cờ thay vì xóa** → phục vụ phân tích "giảm giá ảo"

---

### C. Xuất Dữ Liệu (3 Định Dạng)

```python
# Dữ liệu sạch (CSV)
lam_sach.lay_du_lieu_sach().to_csv(
    "dulieu_sach.csv", 
    index=False, 
    encoding='utf-8-sig'
)

# Ngoại lai (CSV)
ngoai_lai = lam_sach.lay_ngoai_lai()
ngoai_lai.to_csv("ngoai_lai.csv", index=False, encoding='utf-8-sig')

# Dữ liệu sạch (JSON)
lam_sach.lay_du_lieu_sach().to_json(
    "dulieu_sach.json", 
    orient='records', 
    force_ascii=False,
    indent=2
)

# Báo cáo chất lượng (TXT)
lam_sach.xuat_bao_cao_chat_luong("bao_cao_chat_luong.txt")
```

---

## 📊 Schema Dữ Liệu Cuối Cùng

| Cột | Kiểu | Mô tả | Ví dụ |
|-----|------|-------|--------|
| `ma_san_pham` | str | ID sản phẩm | "279218500" |
| `ten_san_pham` | str | Tên đầy đủ | "Ship of Theseus - NXB Trẻ" |
| `nganh_hang` | category | Ngành hàng | "Truyện Tranh, Manga, Comic" |
| `shop` | category | Shop/người bán | "Tiki" |
| `gia` | float | Giá hiện tại (đ) | 46000.0 |
| `gia_goc` | float | Giá gốc (đ) | 50000.0 |
| `ty_le_giam` | float | Tỷ lệ giảm [0,1] | 0.08 |
| `luot_ban` | int | Lượt bán | 273 |
| `danh_gia` | float | Đánh giá [0,5] | 5.0 |
| `url` | str | Link sản phẩm | "https://tiki.vn/..." |
| `da_kiem_tra_gia_ao` | bool | Cờ ngoại lai | False |

---

## 🔍 Ví dụ Chi Tiết: Từ A→Z

### Script hoàn chỉnh

```python
from thu_thap_du_lieu import ThuThapDuLieu, LamSachDuLieu
import pandas as pd

# ==========================================
# 1. THU THẬP DỮ LIỆU
# ==========================================
print("📥 Bước 1: Thu thập dữ liệu...")

bot = ThuThapDuLieu()

# Nếu API hoạt động
# success = bot.goi_api_tiki(ma_nganh_hang="8322", so_trang=5)
# if success:
#     bot.luu_du_lieu("dulieu_tiki_5trang")

# Nếu API không hoạt động, dùng file hiện có
bot.doc_csv("dulieu_nhasach_tiki.csv")

print(f"✓ Thu thập được {len(bot.du_lieu_tho)} sản phẩm")

# ==========================================
# 2. LÀM SẠCH DỮ LIỆU
# ==========================================
print("\n🧹 Bước 2: Làm sạch dữ liệu...")

lam_sach = LamSachDuLieu(bot.du_lieu_tho)
df_sach = lam_sach.lay_du_lieu_sach()

# ==========================================
# 3. PHÂN TÍCH NHANH
# ==========================================
print("\n📊 Bước 3: Phân tích nhanh...")

print(f"\n--- THỐNG KÊ ---")
print(f"Tổng sản phẩm: {len(df_sach)}")
print(f"Ngành hàng: {df_sach['nganh_hang'].nunique()} loại")
print(f"Shop: {df_sach['shop'].nunique()} shop")
print(f"\nGiá:")
print(f"  Min: {df_sach['gia'].min():,.0f} đ")
print(f"  Max: {df_sach['gia'].max():,.0f} đ")
print(f"  TB: {df_sach['gia'].mean():,.0f} đ")
print(f"\nĐánh giá:")
print(f"  TB: {df_sach['danh_gia'].mean():.2f} ⭐")
print(f"\nNgoại lai: {df_sach['da_kiem_tra_gia_ao'].sum()} sản phẩm")

# ==========================================
# 4. LƯUU DỮ LIỆU
# ==========================================
print("\n💾 Bước 4: Lưu dữ liệu...")

# CSV
df_sach.to_csv("dulieu_sach.csv", index=False, encoding='utf-8-sig')
print("✓ CSV: dulieu_sach.csv")

# JSON
df_sach.to_json("dulieu_sach.json", orient='records', 
                force_ascii=False, indent=2)
print("✓ JSON: dulieu_sach.json")

# Ngoại lai
ngoai_lai = lam_sach.lay_ngoai_lai()
ngoai_lai.to_csv("ngoai_lai.csv", index=False, encoding='utf-8-sig')
print(f"✓ Ngoại lai: ngoai_lai.csv ({len(ngoai_lai)} dòng)")

# Báo cáo
lam_sach.xuat_bao_cao_chat_luong("bao_cao_chat_luong.txt")
print("✓ Báo cáo: bao_cao_chat_luong.txt")

print("\n✅ Quy trình hoàn tất!")
```

### Chạy:
```bash
python solution_a.py
```

---

## ⚠️ Những Vấn Đề Thường Gặp

### 1. **API Tiki bị chặn**
- **Nguyên nhân:** Request quá nhanh hoặc headers sai
- **Giải pháp:**
  - Tăng `delay` từ 2s → 3-5s
  - Thử VPN
  - Dùng dữ liệu CSV/JSON hiện có

### 2. **Lỗi encoding (UTF-8)**
- **Lỗi:** `UnicodeDecodeError`
- **Giải pháp:**
  ```python
  pd.read_csv("file.csv", encoding='utf-8-sig')
  ```

### 3. **Dữ liệu thiếu/bất thường**
- Tất cả được xử lý tự động trong `lay_du_lieu_sach()`
- Xem chi tiết trong `bao_cao_chat_luong.txt`

### 4. **NULL quá nhiều**
- Kiểm tra nguồn dữ liệu
- Có thể cần lấy thêm trang từ API

---

## 📎 File Output

Sau khi chạy, sẽ tạo ra:

| File | Mô tả |
|------|-------|
| `dulieu_sach.csv` | Dữ liệu sạch (CSV) |
| `dulieu_sach.json` | Dữ liệu sạch (JSON) |
| `ngoai_lai.csv` | Sản phẩm ngoại lai |
| `bao_cao_chat_luong.txt` | Báo cáo chất lượng |

---

## ✅ Checklist Hoàn Tất

- [x] Thu thập ≥1000 sản phẩm từ API / CSV
- [x] Xử lý thiếu/trùng/sai kiểu/ngoại lai
- [x] Lưu 2+ định dạng (CSV, JSON)
- [x] Viết docstring & comments
- [x] Tạo file requirements.txt
- [x] Viết README hướng dẫn
- [ ] Thực hiện nộp cho thành viên B, C, D

---

## 📞 Liên hệ Hỗ Trợ

- **Thành viên B (Data Analyst):** Yêu cầu: dữ liệu sạch CSV/JSON
- **Thành viên C (ML Engineer):** Yêu cầu: dữ liệu sạch + ngoại lai flag
- **Thành viên D (Product Lead):** Yêu cầu: dữ liệu sạch + báo cáo chất lượng

---

**Lần cập nhật cuối:** 2026-08-05  
**Phiên bản:** v2.0 (Thu thập + Làm sạch hoàn chỉnh)