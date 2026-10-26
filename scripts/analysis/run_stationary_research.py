"""Chạy cải tiến mô hình 3 tháng, đánh giá tín hiệu và khóa ứng viên shadow."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for folder in (ROOT, ROOT/'src'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from scripts.analysis.model_diagnostics import audit_targets
from scripts.analysis.run_model_research import prepare_output, file_hash, write_json
from scripts.analysis.stationary_features import build_stationary_features
from scripts.analysis.stationary_research import run_experiment, choose_candidate, KINDS
from scripts.analysis.stationary_evaluation import select_path, evaluate_candidate
from scripts.analysis.stationary_shadow import algorithm_fingerprint, create_lock, record_latest, shadow_root


def report_markdown(report: dict) -> str:
    """Báo cáo cả kết quả không đạt, phân biệt cải thiện dự báo và hiệu quả danh mục."""
    lines = ['# Kết quả cải tiến mô hình ba tháng', '',
             'Lịch sử đã xem phục vụ phát triển; chưa chứng minh hiệu quả trên dữ liệu mới. Giao diện và mô hình đang hiển thị chưa đổi.', '',
             '## Cách đánh giá', '',
             '- 34 đặc trưng tỷ lệ/biến động, bảy ứng viên khóa trước chạy, train cửa sổ 5 năm.',
             '- Fit đầu tháng, chỉ học nhãn đã đáo hạn; chọn model bằng 24 tháng OOS đã biết, tối thiểu 120 dòng/6 tháng và giảm MAE ít nhất 5% so zero.',
             '- Ngưỡng tín hiệu chỉ thử 0,5%/1%/2%, chọn bằng danh mục quá khứ; thiếu ba giao dịch hoàn tất giữ 1%.',
             '- P(lãi) sigmoid học OOS; Q10 chính bằng point + phân vị residual OOS. GBR Q10 và xác suất empirical là đối chứng, không tự đổi sang phương pháp thắng bảng.',
             '- Danh mục tiền mặt/vàng, quyết định tháng, mua giá bán và bán/định giá theo giá mua; không cộng lợi suất các cửa sổ chồng lấn. Chỉ tính spread, chưa có phí lưu trữ/thuế/phí khác.', '',
             '## Dự báo và danh mục', '',
             '| Ứng viên | MAE (điểm %) | Cải thiện so zero | Lợi suất danh mục | Mức giảm tối đa |',
             '|---|---:|---:|---:|---:|']
    for name, r in report['candidates'].items():
        lines.append(f"| {name} | {r['mae']*100:.2f} | {r['mae_improvement']*100:+.1f}% | {r['portfolio']['total_return']*100:+.1f}% | {r['portfolio']['max_drawdown']*100:.1f}% |")
    n = report['nested']
    lines += [f"| Chọn trước từng tháng | {n['mae']*100:.2f} | {n['mae_improvement']*100:+.1f}% | {n['portfolio']['total_return']*100:+.1f}% | {n['portfolio']['max_drawdown']*100:.1f}% |", '',
              'Lợi suất danh mục là toàn kỳ nghiên cứu, không phải lợi suất năm hoặc lợi suất dự báo.', '',
              '## Ứng viên khóa theo dõi', '',
              f"- Mô hình: **{report['frozen_candidate']}**, ngưỡng {report['frozen_margin']*100:g}%.",
              f"- Đạt toàn bộ tiêu chí phát triển: **{report['candidates'][report['frozen_candidate']]['development_qualified']}**.",
              '- Bản khóa là shadow, không thay mô hình mặc định và không tự cấp validated.',
              '- Nhật ký mới chỉ nhận dự báo phát đúng ngày hiện tại và từ ngày sau ngày khóa; dự báo snapshot cũ chỉ là bản tham chiếu.', '',
              'Chi tiết từng năm, xác suất, Q10, độ đúng Mua/Bán không chồng lấn, bootstrap khối và tiêu chí chưa đạt nằm trong report.json.', '']
    return '\n'.join(lines)


def main() -> None:
    """Lượt fit mới có thư mục riêng; record-only phục vụ nút cập nhật định kỳ."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--record-only', action='store_true')
    args = parser.parse_args()
    modeling = ROOT/'data/lake/modeling'
    if args.record_only:
        report = {str(h): record_latest(modeling, horizon=h) for h in (1,3,5)
                  if (shadow_root(modeling, h)/'active.json').exists()}
        print(json.dumps(report or {'mode': 'shadow', 'status': 'not_configured'}, ensure_ascii=False), flush=True)
        return
    root = modeling/'research'
    folder = (args.output or root/datetime.now(timezone.utc).strftime('stationary-%Y%m%dT%H%M%SZ')).resolve()
    if not folder.is_relative_to(root.resolve()) or folder == root.resolve():
        raise ValueError('Kết quả nghiên cứu phải nằm trong modeling/research.')
    frame_path = modeling/'model_frame_daily.csv'
    source_id = algorithm_fingerprint()
    protected = [frame_path, modeling/'snapshot_forecasts.csv', modeling/'snapshot_validation_report.json',
                 modeling/'paper_trading_ledger.csv', ROOT/'web/data/gold_dashboard_data.json']
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): file_hash(p) for p in protected}
    manifest = dict(status='research_only', source_id=source_id, started_at=datetime.now(timezone.utc).isoformat(),
                    protected_sha256=hashes, candidates=list(KINDS), horizon_months=3,
                    warmup_start='2021-01-01', evaluation_start='2023-01-01',
                    margins=[.005, .01, .02], selection='monthly_24m_matured_oos_5pct_improvement',
                    activation='shadow_only', calibration='sigmoid_oos_24m_residual_q10')
    prepare_output(folder, manifest)
    f = pd.read_csv(frame_path, low_memory=False).sort_values('date').reset_index(drop=True)
    f['date'] = pd.to_datetime(f.date)
    audit = audit_targets(f, (3,))
    write_json(folder/'target_audit.json', audit)
    if any(a['return_mismatches'] or a['exit_mismatches'] or a['invalid_price_rows'] for a in audit):
        raise ValueError('Dữ liệu không qua kiểm tra nhãn/giá; dừng trước fit.')
    features = build_stationary_features(f)
    write_json(folder/'features.json', {'names': list(features), 'missing_rate': features.isna().mean().to_dict()})
    predictions = run_experiment(f)
    predictions.to_csv(folder/'predictions.csv', index=False, encoding='utf-8')
    print('Đang đánh giá danh mục, xác suất, Q10 và lựa chọn trước từng tháng…', flush=True)
    path, choices = select_path(predictions, f)
    path.to_csv(folder/'selected_path.csv', index=False, encoding='utf-8')
    write_json(folder/'selections.json', choices)
    evaluation = predictions.loc[predictions.date.ge('2023-01-01')]
    candidates = {name: evaluate_candidate(rows, f) for name, rows in evaluation.groupby('candidate')}
    nested = evaluate_candidate(path, f)
    # Chọn ứng viên ML từ cửa sổ trước đầu tháng hiện tại cho shadow. Nếu
    # zero thắng, vẫn có thể theo dõi ML tốt nhất, nhưng không gọi nó đủ chuẩn.
    cutoff = f.date.max().to_period('M').start_time
    selection = choose_candidate(predictions, cutoff)
    learning = ('ridge', 'elasticnet', 'rf_small', 'boosting')
    candidate = min(learning, key=lambda k: (selection['scores'].get(k, float('inf')), k))
    margin = choices[-1]['margin'] if choices and choices[-1]['candidate'] == candidate else .01
    report = dict(status='research_only', independent_validation=False, snapshot_date=str(f.date.max().date()),
                  candidates=candidates, nested=nested, current_selection=selection,
                  frozen_candidate=candidate, frozen_margin=margin)
    current_report = modeling/'snapshot_historical_report.json'
    if current_report.exists():
        historical = json.loads(current_report.read_text(encoding='utf-8'))
        report['existing_model_reference'] = next((h for h in historical['horizons'] if h['horizon_months']==3), {})
        report['existing_model_reference_notice'] = 'Mô hình cũ đóng băng năm, chỉ là tham chiếu; đối chứng chính cùng lịch tháng nằm trong candidates.'
    if algorithm_fingerprint() != source_id or any(file_hash(p) != hashes[str(p.relative_to(ROOT)).replace('\\', '/')] for p in protected):
        raise ValueError('Mã/dữ liệu thay đổi giữa lượt chạy; không công nhận báo cáo hoàn tất.')
    write_json(folder/'report.json', report)
    (folder/'report.md').write_text(report_markdown(report), encoding='utf-8')
    initial = folder/'frozen_calibration.csv'
    predictions.loc[predictions.candidate.eq(candidate)].to_csv(initial, index=False, encoding='utf-8')
    protocol = create_lock(modeling/'stationary_shadow', initial, candidate=candidate, margin=margin, now=datetime.now(timezone.utc))
    shadow = record_latest(modeling)
    manifest.update(completed_at=datetime.now(timezone.utc).isoformat(), protected_artifacts_unchanged=True,
                    shadow_protocol_id=protocol['protocol_id'], validation_start=protocol['validation_start'])
    write_json(folder/'manifest.json', manifest)
    print(f'Hoàn tất: {folder}; shadow {protocol["protocol_id"]}, trạng thái {shadow["status"]}.', flush=True)


if __name__ == '__main__':
    main()
