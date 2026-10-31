# Vàng hôm nay — Nghiên cứu vàng hằng ngày

Website: **https://nguyenvanchi-cmd.github.io/vang-dashboard/**

Dashboard theo dõi giá vàng thế giới và trong nước, cập nhật tự động mỗi sáng:

- **Tổng quan**: giá XAU/USD, nhận định trong ngày của Claude (xu hướng theo khung 15m, 3 tầng Gốc – Thân – Ngọn), trạng thái kỹ thuật, quy luật lịch sử đang xảy ra, lịch tin và tin chọn lọc.
- **Biểu đồ & lịch sử**: nến ngày với EMA 20/50/200, RSI, MACD; bảng lịch sử theo ngày có tìm kiếm, lọc và tải CSV.
- **Định lượng & học máy**: nghiên cứu sự kiện, thống kê theo thứ và tháng, kiểm định chiến lược có tính phí mua bán, so sánh Mua nền với chiến dịch 70–20–10, mô hình học máy kiểm tra trượt theo năm.
- **Thị trường trong nước**: giá theo thương hiệu, tỷ giá, chênh lệch SJC so với giá thế giới quy đổi.

## Cách hoạt động

| Thời điểm (giờ VN) | Việc |
|---|---|
| 06:15, thứ Hai – thứ Bảy | GitHub Actions lấy giá XAU/USD, tỷ giá, giá trong nước; chạy `scripts/analyze.py`; triển khai website |
| 06:42 | Claude đọc biểu đồ và tin tức, đẩy `data/claude_daily.json`; website tự dựng lại |
| 16:30, thứ Hai – thứ Bảy | Cập nhật giá trong nước buổi chiều |

Có thể chạy tay: tab **Actions → Cập nhật dữ liệu và website → Run workflow**.

## Cấu trúc

- `scripts/fetch_data.py`: lấy dữ liệu (Yahoo GC=F, Dukascopy/Stooq dự phòng, Vietcombank, SJC, PNJ).
- `scripts/analyze.py`: chỉ báo, thống kê, kiểm định, học máy; xuất `site/data/*.json`.
- `data/`: lịch sử giá theo ngày, tỷ giá, giá trong nước, nhận định của Claude.
- `site/`: website tĩnh (HTML, CSS, JS thuần + TradingView Lightweight Charts).

*Đây là nghiên cứu tham khảo, không phải khuyến nghị mua bán.*
