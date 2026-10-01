# 1. Sử dụng Python 3.11 bản slim để nhẹ và nhanh
FROM python:3.11-slim

# 2. Thiết lập thư mục làm việc trong container
WORKDIR /app

# 3. Copy file requirements.txt vào trước để tận dụng cache của Docker
COPY requirements.txt .

# 4. Cài đặt các thư viện cần thiết
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# 5. Copy toàn bộ mã nguồn còn lại vào container
COPY . .

# 6. Mở cổng 3000 (vì trong code lo.py có SERVER_PORT = 3000)
EXPOSE 3000

# 7. Lệnh khởi chạy bot khi container bắt đầu
CMD ["python", "lo2.py"]
