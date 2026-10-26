"""Dựng lại quy đổi, so sánh mô hình và công bố dự báo có kiểm tra P/Q10."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
for folder in (ROOT, ROOT/'src'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import pandas as pd
from gold_collectors.modeling import ModelingConfig, build_model_frame
from gold_collectors.units import GRAMS_PER_LUONG, GRAMS_PER_TROY_OUNCE
from scripts.processing.improve_premium_coverage import build_improved
from scripts.analysis.model_diagnostics import audit_targets
from scripts.analysis.run_model_research import file_hash, write_json
from scripts.analysis.stationary_research import run_experiment
from scripts.analysis.forecast_selection import select_research_forecast
from scripts.analysis.stationary_evaluation import evaluate_candidate
from scripts.analysis.stationary_shadow import algorithm_fingerprint, create_lock, record_latest, shadow_root
from scripts.analysis.stationary_activation import activate_candidate
from scripts.analysis.active_snapshot import refresh_active_pipeline


def main():
    """Chạy từng kỳ hạn trên cùng dữ liệu; chỉ đổi registry sau khi đủ kết quả.

    Không tải thêm giá/tin và không thay tiêu chí kiểm định. Lịch sử đã xem
    vẫn phục vụ nghiên cứu; bản khóa mới bắt đầu bằng chứng ở ngày kế tiếp.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    lake, modeling = ROOT/'data/lake', ROOT/'data/lake/modeling'
    output = args.output.resolve()
    if not output.is_relative_to((modeling/'research').resolve()) or output == (modeling/'research').resolve():
        raise ValueError('Báo cáo phải nằm trong một thư mục con mới của modeling/research.')
    output.mkdir(parents=True, exist_ok=False)
    source = algorithm_fingerprint()
    protected = {name: file_hash(modeling/name) for name in ('model_frame_daily.csv','snapshot_forecasts.csv','active_prediction_model.json')}
    shutil.copyfile(modeling/'snapshot_forecasts.csv', output/'previous_snapshot_reference.csv')
    write_json(output/'manifest.json', dict(status='running', source_id=source, previous_sha256=protected,
        candidates=['zero','rf_small','rf_median'], selection='mae_5pct_3_stable_years_positive_block_interval',
        forecast_selection='best_horizon_ml_research_when_unqualified',
        independent_validation=False, started_at=datetime.now(timezone.utc).isoformat()))

    print('Đang dựng lại premium từ khối lượng chuẩn…', flush=True)
    premium, metadata = build_improved(argparse.Namespace(gold_tolerance_days=4, fx_tolerance_days=4, target_missing_rate=.1))
    premium.to_csv(lake/'pipeline_output_premium_enriched.csv', index=False, encoding='utf-8')
    metadata['audit'].to_csv(lake/'quality/premium_coverage_audit.csv', index=False, encoding='utf-8')
    write_json(lake/'quality/premium_coverage_summary.json', metadata['summary'])
    frame = build_model_frame(ModelingConfig(data_lake=lake, output_dir=modeling))
    frame.to_csv(modeling/'model_frame_daily.csv', index=False, encoding='utf-8')
    write_json(modeling/'feature_columns.json', list(frame.attrs['feature_columns']))
    audit = audit_targets(frame, (1,3,5))
    write_json(output/'target_audit.json', audit)
    if any(row['return_mismatches'] or row['exit_mismatches'] or row['invalid_price_rows'] for row in audit):
        raise ValueError('Giá hoặc nhãn tháng lịch không hợp lệ; dừng trước huấn luyện.')
    frame['date'] = pd.to_datetime(frame.date)
    cutoff = frame.date.max().to_period('M').start_time
    digest = file_hash(modeling/'model_frame_daily.csv')
    reports, selections = {}, {}
    for horizon in (1,3,5):
        print(f'Đang so sánh zero, RF cũ và RF trung vị: {horizon} tháng…', flush=True)
        predictions = run_experiment(frame, kinds=('zero','rf_small','rf_median'), horizon=horizon)
        predictions.to_csv(output/f'predictions_{horizon}m.csv', index=False, encoding='utf-8')
        selection = select_research_forecast(predictions, cutoff, horizon=horizon)
        selections[str(horizon)] = selection
        reports[str(horizon)] = {name: evaluate_candidate(group.loc[group.date.ge('2023-01-01')], frame, horizon=horizon)
                                 for name, group in predictions.groupby('candidate')}
        selected = predictions.loc[predictions.candidate.eq(selection['candidate'])]
        selected.to_csv(output/f'calibration_{horizon}m.csv', index=False, encoding='utf-8')
        # Lưu ngay kết quả mỗi kỳ hạn để lượt chạy dừng giữa chừng vẫn có
        # bằng chứng nghiên cứu; registry chưa đổi khi mới xong một phần.
        write_json(output/'selection.json', selections)
        write_json(output/'candidate_reports.json', reports)

    if algorithm_fingerprint() != source or file_hash(modeling/'model_frame_daily.csv') != digest:
        raise ValueError('Mã hoặc frame đã đổi trong lúc so sánh; không kích hoạt.')
    protocols = {}
    for horizon in (1,3,5):
        protocols[str(horizon)] = create_lock(shadow_root(modeling,horizon), output/f'calibration_{horizon}m.csv',
            candidate=selections[str(horizon)]['candidate'], margin=.01, now=datetime.now(timezone.utc), horizon=horizon,
            selection_evidence=selections[str(horizon)])['protocol_id']
        record_latest(modeling, horizon=horizon)
    activation = activate_candidate(modeling, horizons=(1,3,5))
    refresh_active_pipeline(lake)
    latest = {str(h): json.loads((shadow_root(modeling,h)/'latest.json').read_text(encoding='utf-8')) for h in (1,3,5)}
    report = dict(status='research_only', independent_validation=False, source_id=source,
        snapshot_date=str(frame.date.max().date()), frame_sha256=digest,
        units=dict(grams_per_luong=GRAMS_PER_LUONG, grams_per_troy_ounce=GRAMS_PER_TROY_OUNCE),
        candidates=reports, selections=selections, protocols=protocols, activation=activation, latest=latest)
    write_json(output/'report.json', report)
    write_json(modeling/'forecast_repair_report.json', {'report_path':str(output.relative_to(ROOT)),
        'status':'research_only','snapshot_date':report['snapshot_date'],'selections':selections})
    write_json(output/'manifest.json', dict(status='complete', source_id=source, previous_sha256=protected,
        frame_sha256=digest, protocols=protocols, independent_validation=False,
        completed_at=datetime.now(timezone.utc).isoformat()))
    print(f'Đã dựng lại dữ liệu và dự báo: {output}', flush=True)


if __name__ == '__main__':
    main()
