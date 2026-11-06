"""Tạo bản đọc mã nguồn có chú thích mà vẫn giữ nguyên bản khóa mô hình.

Chỉ ghi vào docs/presentation/code. Các bản sao dùng để giải thích khi
thuyết trình, không phải module được import bởi pipeline. Mỗi bản được
so sánh cây cú pháp với nguồn để bảo đảm chỉ thêm comment, không sửa logic.
"""

from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'docs/presentation/code'

# Mỗi mốc phải xuất hiện đúng một lần. Nếu nguồn đã đổi, dừng để người
# bảo trì kiểm tra vị trí giải thích, không chèn comment nhầm khối nghiệp vụ.
SECTIONS = {
    '01_targets.py': ('src/gold_collectors/modeling/targets.py', [
        ('    frame = frame.sort_values', '    # Giá mua là giá cửa hàng trả cho người bán vàng; giá bán là số tiền\n    # nhà đầu tư trả khi mua. Vì vậy lợi suất phải tính tương lai mua / hiện tại bán.'),
        ('        known = exit_positions', '        # Chỉ gán nhãn khi đã có báo giá thoát trong dữ liệu. Các dự báo\n        # chưa đủ kỳ hạn giữ NaN, tuyệt đối không xem là lợi suất bằng 0.'),
        ('        frame[f"net_return_', '        # Lợi suất ròng đã phản ánh chênh lệch mua–bán: mua 100 triệu,\n        # bán lại được 103 triệu thì nhãn là 0,03, tức lãi 3%.'),
    ]),
    '02_stationary_features.py': ('scripts/analysis/stationary_features.py', [
        ('    if dates.isna()', '    # shift và rolling phụ thuộc thứ tự thời gian; ngày trùng hoặc đảo\n    # thứ tự sẽ khiến biến quá khứ không còn đúng ý nghĩa kinh tế.'),
        ('    def numeric(name):', '    # Nguồn thiếu được biểu diễn bằng NaN. Điền thiếu phải học trong\n    # tập train, không lấy thống kê của toàn bộ lịch sử gồm tương lai.'),
        ('    cols = {', '    # spread_ratio đo chi phí vào–ra ngay tại thời điểm mua; momentum\n    # đo tốc độ thay đổi giá, còn volatility đo mức biến động gần đây.'),
        ('    for window in (21, 63, 126):', '    # Khoảng cách tới trung bình và đỉnh/đáy cho biết trạng thái xu hướng.\n    # 21/63/126 là số dòng quá khứ, không phải định nghĩa kỳ hạn tháng lịch.'),
        ("    gold = numeric('gold_futures", '    # Dữ liệu quốc tế trễ một dòng để bảo thủ về thời điểm công bố.\n    # Không đưa nhãn tương lai, tiêu đề tin gắn hồi cứu vào nhóm đầu vào này.'),
    ]),
    '03_stationary_research.py': ('scripts/analysis/stationary_research.py', [
        ('def make_model(', '# Mỗi loại là một cấu hình đã định trước. Không tăng/giảm tham số\n# sau khi nhìn kết quả cuối rồi gọi lại đó là kiểm định độc lập.'),
        ("    elif kind == 'rf_small':", '    # RF nhỏ giới hạn độ sâu và số mẫu mỗi lá để hạn chế học thuộc nhiễu.\n    # Cả hai RF đều 100 cây; khác biệt không nằm ở số cây.'),
        ("    elif kind == 'rf_median':", '    # absolute_error dùng trung vị trong lá cây, phù hợp với MAE và\n    # giảm ảnh hưởng của vài đợt tăng giá bất thường lên mức dự báo.'),
        ('    return make_pipeline(SimpleImputer', '    # Pipeline fit imputer/scaler trên train. Khi dự báo test chỉ dùng\n    # phép biến đổi đã học, tránh rò rỉ thống kê của giai đoạn đánh giá.'),
        ('    hold = (1 + y)', '    # RF cũ học biến động giá mua lại, rồi đổi sang lợi suất mua mới.\n    # RF trung vị học trực tiếp y = lợi suất ròng; hai biến thể khác cả target và loss.'),
        ('def calibrate(', '# P(lãi) là ước lượng xác suất lợi suất >0; Q10 là phân vị thấp 10%.\n# Cả hai cần sai số ngoài mẫu đã đáo hạn, không dùng residual train để tự chấm.'),
        ('        train_mask = (f.date.ge', '        # Hai điều kiện đều cần: ngày phát thuộc quá khứ VÀ ngày thoát\n        # đã trước đầu fold. Một mẫu phát trước fold vẫn có thể chưa đáo hạn.'),
        ('def select_deployable_candidate(', '# Chọn theo MAE và độ ổn định theo năm/khối thời gian. Thắng trong\n# hai RF không tự chứng minh đã thắng baseline zero hoặc đủ tin cậy giao dịch.'),
    ]),
    '04_snapshot_validation.py': ('scripts/analysis/snapshot_validation.py', [
        ('def model_source_fingerprint(', '# Mã kiểm tra bao gồm nội dung nguyên tệp và phiên bản thư viện.\n# Vì vậy tài liệu đọc có comment nằm riêng, không sửa dấu vân tay bản khóa.'),
        ('def record_forecasts(', '# Ghi dự báo trước khi biết kết quả để tạo bằng chứng tiến cứu.\n# Không được viết lại bản ghi cũ theo dự báo hoặc giá vừa biết hôm nay.'),
        ('def matured_forecasts(', '# Chỉ đánh giá khoản đầu tư đã tới ngày tròn tháng và có báo giá SJC\n# hợp lệ để thoát. Chưa đáo hạn không đồng nghĩa dự báo đúng hoặc sai.'),
        ('def evaluate_horizon(', '# Trạng thái validated cần vượt toàn bộ cổng về số mẫu, thời gian,\n# MAE, xác suất và rủi ro. validation_pending nghĩa là còn thiếu bằng chứng.'),
    ]),
    '05_refresh_pipeline.py': ('scripts/pipeline/refresh_latest_forecast.py', [
        ('def run_step(', '# Dùng cùng Python và thư mục gốc cho mọi bước; check=True khiến lỗi\n# nguồn được báo lên thay vì tiếp tục công bố một dashboard có dữ liệu cũ.'),
        ('def refresh(', '# Điểm điều phối: thu thập → bảng quốc tế → premium → model frame\n# và dự báo → nhật ký thử nghiệm → đối chiếu ngày đầu ra.'),
        ('    if not skip_collect:', '    # --skip-collect chỉ tái dùng lake hiện có, không có nghĩa đã cập nhật\n    # thị trường tới hôm nay. Khi demo cần đọc ngày snapshot thực tế.'),
        ('    snapshot = pd.read_csv', '    # Cùng một lượt cập nhật phải có đủ 1/3/5 tháng và cùng ngày dữ liệu\n    # giữa CSV dự báo, model frame và JSON giao diện trước khi báo thành công.'),
    ]),
    '06_active_snapshot.py': ('scripts/analysis/active_snapshot.py', [
        ('def publish_active_snapshots(', '# Một dự báo được dùng chung cho CSV, kiểm định và web. Không lấy\n# điểm dự báo từ mô hình này rồi ghép P(lãi)/Q10 của một mô hình khác.'),
        ("    latest = {str(h):", '    # Nạp và xác minh đủ ba kỳ hạn trước khi ghi tệp. Bản khóa lưu cấu\n    # hình/ngữ nghĩa chiến dịch, còn trọng số có thể học lại theo đúng quy trình.'),
        ("    temporary = modeling/'snapshot_forecasts", '    # Ghi tệp tạm rồi thay thế giúp người đọc không thấy CSV đang viết dở.\n    # Đây không phải giao dịch nguyên tử cho toàn bộ các tệp của pipeline.'),
        ('def refresh_active_pipeline(', '# Registry quyết định tuyến model. Khi reliability_v2 được chọn mà\n# bản khóa sai, phải báo lỗi; không âm thầm quay về RF cũ để che thất bại.'),
    ]),
    '07_build_model_frame.py': ('src/gold_collectors/modeling/features.py', [
        ('def _last_quote_per_day(', '# Chuẩn hóa báo giá theo ngày, chỉ giữ giá mua dương và giá bán không\n# thấp hơn giá mua; chọn báo giá cuối ngày làm mốc vào lệnh nhất quán.'),
        ('def _merge_global_asof(', '# Ghép as-of nhìn về quá khứ: chỉ dùng quan sát quốc tế đã khả dụng,\n# tránh ghép chỉ theo nhãn ngày mà vô tình đọc thông tin công bố muộn.'),
        ('def _merge_macro_asof(', '# Dữ liệu vĩ mô có kỳ thống kê và ngày công bố khác nhau. Biến tháng\n# trước chưa được dùng nếu ngày available_from còn sau ngày dự báo.'),
        ('def _add_lagged_features(', '# Các độ trễ/thống kê chỉ tóm tắt quá khứ. Nhãn future_buy/net_return\n# phải tách khỏi feature_columns để mô hình không nhìn trước kết quả.'),
        ('def build_model_frame(', '# Đầu ra là bảng một ngày/một dòng cùng metadata đặc trưng. Đây là\n# lớp chuẩn bị dữ liệu, không tự xác nhận độ chính xác hay trạng thái validated.'),
    ]),
}


def main() -> None:
    """Tạo đủ bản đọc trong bộ nhớ, kiểm tra logic rồi mới ghi UTF-8 không BOM."""
    rendered, manifest = {}, {}
    for name, (relative, sections) in SECTIONS.items():
        source = (ROOT/relative).read_text(encoding='utf-8-sig')
        annotated = source
        for anchor, comment in sections:
            if annotated.count(anchor) != 1:
                raise ValueError(f'Mốc chú thích không duy nhất trong {relative}: {anchor}')
            annotated = annotated.replace(anchor, comment+'\n'+anchor, 1)
        header = (f'# BẢN ĐỌC THUYẾT TRÌNH — nguồn vận hành: {relative}\n'
                  '# Chỉ thêm comment tiếng Việt; không import hoặc chạy bản sao này.\n'
                  '# Tạo lại: python scripts/reporting/prepare_presentation_sources.py\n\n')
        annotated = header+annotated
        # Comment không có trong AST: cây cú pháp giống nhau là bằng chứng
        # bản giải thích giữ nguyên hàm, điều kiện, chuỗi tiếng Việt và công thức.
        if ast.dump(ast.parse(source)) != ast.dump(ast.parse(annotated)):
            raise ValueError(f'Bản đọc thay đổi logic: {relative}')
        rendered[name] = annotated
        manifest[name] = dict(source=relative, source_sha256=sha256((ROOT/relative).read_bytes()).hexdigest(),
                              annotated_sha256=sha256(annotated.encode('utf-8')).hexdigest(), ast_identical=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        # Cố định LF để hash của chuỗi UTF-8 khớp byte trên đĩa cả Windows
        # lẫn Linux; chuyển ngầm LF sang CRLF sẽ làm manifest sai dù AST giống.
        (OUTPUT/name).write_text(content, encoding='utf-8', newline='\n')
    (OUTPUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(f'Created {len(rendered)} annotated copies; all ASTs identical to operational sources.')


if __name__ == '__main__':
    main()
