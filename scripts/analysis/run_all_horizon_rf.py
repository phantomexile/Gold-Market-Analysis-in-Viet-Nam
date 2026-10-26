"""Huấn luyện RF cải tiến và kích hoạt đồng bộ ba kỳ hạn lịch 1/3/5 tháng."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
for folder in (ROOT, ROOT/'src'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from scripts.analysis.model_diagnostics import audit_targets
from scripts.analysis.run_model_research import write_json, file_hash
from scripts.analysis.stationary_research import run_experiment
from scripts.analysis.stationary_evaluation import evaluate_candidate
from scripts.analysis.stationary_shadow import algorithm_fingerprint, create_lock, shadow_root, record_latest
from scripts.analysis.stationary_activation import activate_candidate


def main():
    """Dùng cùng tham số RF, nhưng không dùng chung nhãn hoặc residual giữa kỳ hạn.

    Lịch sử ngoài mẫu phục vụ hiệu chỉnh và báo cáo nghiên cứu. Mỗi kỳ hạn
    bắt đầu bằng chứng mới từ ngày sau khi khóa, không nhận thành tích cũ.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    modeling = ROOT/'data/lake/modeling'
    output = args.output.resolve()
    if not output.is_relative_to((modeling/'research').resolve()):
        raise ValueError('Báo cáo phải nằm trong modeling/research.')
    output.mkdir(parents=True, exist_ok=False)
    source = algorithm_fingerprint()
    path = modeling/'model_frame_daily.csv'
    digest = file_hash(path)
    frame = pd.read_csv(path, low_memory=False)
    frame['date'] = pd.to_datetime(frame.date)
    audit = audit_targets(frame, (1,3,5))
    write_json(output/'target_audit.json', audit)
    if any(a['return_mismatches'] or a['exit_mismatches'] or a['invalid_price_rows'] for a in audit):
        raise ValueError('Nhãn hoặc giá không hợp lệ; chưa huấn luyện.')
    reports = {}
    for horizon in (1,3,5):
        predictions = run_experiment(frame, kinds=('rf_small','zero'), horizon=horizon)
        predictions.to_csv(output/f'predictions_{horizon}m.csv', index=False, encoding='utf-8')
        rf = predictions.loc[predictions.candidate.eq('rf_small')]
        rf.to_csv(output/f'calibration_{horizon}m.csv', index=False, encoding='utf-8')
        reports[str(horizon)] = evaluate_candidate(rf.loc[rf.date.ge('2023-01-01')], frame, horizon=horizon)
    # Chỉ kích hoạt khi mọi kỳ hạn hoàn tất trên cùng dữ liệu và mã nguồn.
    if algorithm_fingerprint() != source or file_hash(path) != digest:
        raise ValueError('Mã/dữ liệu đổi trong lúc huấn luyện; chưa kích hoạt.')
    protocols = {}
    for horizon in (1,3,5):
        protocol = create_lock(shadow_root(modeling, horizon), output/f'calibration_{horizon}m.csv',
                               candidate='rf_small', margin=.01, now=datetime.now(timezone.utc), horizon=horizon)
        protocols[str(horizon)] = protocol['protocol_id']
        record_latest(modeling, horizon=horizon)
    activation = activate_candidate(modeling, horizons=(1,3,5))
    write_json(output/'report.json', dict(status='research_only', independent_validation=False,
        snapshot_date=str(frame.date.max().date()), source_id=source, frame_sha256=digest,
        candidates=reports, protocols=protocols, activation=activation))
    print(f'Đã áp dụng RF cải tiến cho 1/3/5 tháng: {output}', flush=True)


if __name__ == '__main__':
    main()
