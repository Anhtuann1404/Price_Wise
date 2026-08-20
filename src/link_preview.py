import requests
from bs4 import BeautifulSoup
import streamlit as st

def lay_thong_tin_link(url):
    try:
        # Thêm User-Agent để các trang web không chặn yêu cầu
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Tìm các thẻ chứa ảnh, tiêu đề và mô tả
        image = soup.find("meta", property="og:image")
        title = soup.find("meta", property="og:title")
        desc = soup.find("meta", property="og:description")
        
        return {
            "image": image["content"] if image else None,
            "title": title["content"] if title else "Không có tiêu đề",
            "desc": desc["content"] if desc else ""
        }
    except Exception as e:
        return None # Trả về None nếu link lỗi hoặc web chặn