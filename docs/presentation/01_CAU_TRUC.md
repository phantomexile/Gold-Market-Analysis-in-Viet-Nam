# 01 — Cấu trúc dự án theo trách nhiệm

```text
Gold-Market-Analysis-in-Viet-Nam/
├── README.md                     Điểm bắt đầu và cách cài đặt
├── configs/                      Cấu hình nguồn và tiêu chí kiểm định
├── src/gold_collectors/           Thư viện thu thập, chuẩn hóa và nghiệp vụ
│   └── modeling/                 Ghép dữ liệu, tạo nhãn, huấn luyện, đánh giá
├── scripts/
│   ├── collection/               Thu thập dữ liệu bên ngoài
│   ├── processing/               Chuẩn hóa, ghép bảng, tính premium
│   ├── pipeline/                 Điều phối cập nhật; giữ đường dẫn cũ
│   ├── analysis/                 Dự báo đang dùng, nghiên cứu và kiểm định
│   ├── reporting/                Báo cáo, hình và bản mã thuyết trình
│   └── maintenance/              Bảo trì, phục hồi và công cụ lịch sử
├── data/lake/                    Dữ liệu nguồn và các bảng xử lý
│   └── modeling/                 Frame, registry, snapshot, nhật ký kiểm định
│       └── research/             Bằng chứng từng lượt thử nghiệm
├── web/                          Server, HTML, CSS, JavaScript, JSON dashboard
├── notebooks/                    Phân tích khám phá có thể đọc theo ô
├── tests/                        Kiểm thử nghiệp vụ và tương thích
├── docs/
│   ├── presentation/             Nội dung thuyết trình và mã có chú thích
│   ├── reports/modeling/         Báo cáo mô hình theo ngày
│   ├── figures/                  Hình minh họa
│   └── superpowers/              Kế hoạch và thiết kế triển khai
└── output/presentation/          Vị trí dành cho sản phẩm trình bày xuất ra
```

Không cần giới thiệu lần lượt tất cả tệp. Trình bày theo chuỗi **collection → processing → modeling → validation → web**; sau đó mở [bản đồ mã đầy đủ](../SOURCE_CODE_MAP.md) nếu được hỏi sâu.

Trong `scripts/pipeline/` có một số tệp chỉ chuyển tiếp sang thư mục mới để các lệnh cũ vẫn chạy. Không nhầm chúng với nơi triển khai nghiệp vụ. Xem [hướng dẫn scripts](../../scripts/README.md) và [phân nhóm analysis](../../scripts/analysis/README.md).

`.cache`, `.pytest_cache`, `.chart-data-*` và `.presentation-build` là dữ liệu làm việc tạm của công cụ, không phải phần nghiệp vụ cần trình bày. Không tự xóa khi chúng có thể thuộc một phiên làm việc khác.
