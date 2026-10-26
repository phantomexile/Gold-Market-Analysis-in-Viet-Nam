# Áp dụng mô hình cải tiến cho kỳ hạn ba tháng

**Yêu cầu đã duyệt:** Người dùng yêu cầu áp dụng ngay mô hình mới dù kiểm định chưa đạt. Dùng RF cải tiến đã khóa cho ba tháng, giữ 1/5 tháng và giao diện tín hiệu trực tiếp.

- [x] Kiểm thử RED/GREEN chuyển đồng bộ point/P/Q10/status, không đổi 1/5 tháng.
- [x] Tạo active_prediction_model.json chọn đúng candidate/protocol/source/margin; không thay thuật toán hoặc reset campaign khi chỉ đổi tuyến hiển thị.
- [x] Mỗi lần dựng dashboard gọi collector để lấy dự báo mới trước khi xuất JSON, tương thích luồng cập nhật hiện tại.
- [x] Bản khóa/ngày/giá sai: Quan sát và bỏ số liệu cũ; không tự fallback RF cũ cho ba tháng.
- [x] Không kế thừa cờ mô phỏng/thành tích kiểm định cũ. Trạng thái mới vẫn pending; lịch sử của mô hình cũ không gán cho mô hình mới.
- [x] Kích hoạt thật, dựng lại JSON và kiểm tra giao diện 1440/390px.
- [x] Rà soát độc lập; sửa cờ simulation_buy_signal bằng regression RED→GREEN.

## Kết quả

- Active candidate `rf_small`, protocol `9a00600ea79882241950320f`, margin1%, horizon3.
- Snapshot 24/10/2026: lợi suất mua mới +3,08%, giữ thêm so bán ngay +5,31%, P(lãi)68,74%, Q10−14,25%; tín hiệu Mua. 1 tháng Quan sát, 5 tháng Mua như trước.
- Source của point/P/Q10 cùng từ stationary_shadow/latest.json được làm mới. File snapshot_forecasts.csv cũ giữ làm tham chiếu/kiểm định; dashboard chính ba tháng dùng ứng viên đang được chọn.
- Các thư viện khi cập nhật phải khớp bản khóa; sai thì Quan sát và báo lý do, không tự cấp validated hoặc đổi campaign.
- Có lỗi ghi JSON thoáng qua ở lần dựng đầu (OSError22); kiểm tra file và chạy lại cùng lệnh thành công, không sửa quyền hoặc xóa dữ liệu.
- Không đổi mô hình/thuật toán đã khóa, không viết lệnh giao dịch, không commit/deploy.
