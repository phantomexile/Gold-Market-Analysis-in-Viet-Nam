"""Công bố cùng dự báo đang kích hoạt cho CSV, kiểm định, sổ mô phỏng và web."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import pandas as pd

from .run_model_research import write_json
from .snapshot_validation import _checksum
from .stationary_activation import load_active_forecast

PIPELINE_VERSION = 'reliability_v2'


def publish_active_snapshots(modeling: Path) -> dict:
    """Đọc đủ ba bản khóa trước khi ghi; không trộn đầu ra tuyến huấn luyện khác.

    CSV giữ số liệu được phép công bố. Số liệu nghiên cứu chưa đạt nằm trong
    latest.json và nhật ký bất biến, phục vụ kiểm chứng sau khi đáo hạn.
    """
    dates = pd.read_csv(modeling/'model_frame_daily.csv',usecols=['date'])
    snapshot = str(dates.date.max())
    latest = {str(h):load_active_forecast(modeling,snapshot,horizon=h) for h in (1,3,5)}
    protocols = {key:row['validation']['protocol_id'] for key,row in latest.items()}
    report_id = _checksum({'horizon_protocols':protocols})[:24]
    rows = []
    generated = datetime.now(timezone.utc).isoformat()
    for h in (1,3,5):
        row = latest[str(h)]
        selection=row.get('forecast_selection',{})
        rows.append(dict(generated_at=generated,snapshot_date=snapshot,horizon_months=h,horizon_label=f'{h} tháng',
            target_date=(pd.Timestamp(snapshot)+pd.DateOffset(months=h)).date().isoformat(),
            exit_rule='first_valid_sjc_quote_on_or_after_target_date',point_model=f"stationary_{row['candidate']}_{h}m",
            q10_model='adaptive_temporal_oos_q10_v2',predicted_net_return=row['predicted_net_return'],
            q10_predicted_net_return=row['q10_predicted_net_return'],prob_return_positive=row['prob_return_positive'],
            probability_method=row['probability_method'],calibration_rows=row['calibration_rows'],
            entry_sell_price=row['entry_sell_price'],baseline_probability=row['baseline_probability'],baseline_q10=row['baseline_q10'],
            # Trạng thái kiểm định tiến cứu và tín hiệu trực tiếp vẫn tách biệt.
            # Không gán Mua đã kiểm định chỉ vì dự báo điểm vượt ngưỡng.
            buy_signal=False,status=row['validation']['status'],validation_protocol_id=report_id,
            model_protocol_id=row['validation']['protocol_id'],forecast_role=selection.get('forecast_role','model'),
            baseline_candidate=selection.get('baseline_candidate','zero'),
            point_qualified=selection.get('improved_over_baseline'),
            point_model_mae=selection.get('point_comparison',{}).get('mae'),
            baseline_mae=selection.get('point_comparison',{}).get('zero_mae')))
    report = dict(generated_at=generated,snapshot_date=snapshot,protocol_id=report_id,horizon_protocols=protocols,
                  validation_start=max(row['validation']['validation_start'] for row in latest.values()),
                  horizons=[row['validation'] for row in latest.values()])
    temporary = modeling/'snapshot_forecasts.csv.tmp'
    pd.DataFrame(rows).to_csv(temporary,index=False,encoding='utf-8')
    temporary.replace(modeling/'snapshot_forecasts.csv')
    write_json(modeling/'snapshot_validation_report.json',report)
    return latest


def refresh_active_pipeline(lake: Path) -> bool:
    """Nhánh cập nhật thường ngày của mô hình đã sửa; trả False cho cấu hình cũ.

    Khi registry đã chọn pipeline mới, lỗi bản khóa phải dừng lượt cập nhật,
    không âm thầm huấn luyện RF cũ rồi đưa số liệu khác vào sổ mô phỏng.
    """
    modeling = lake/'modeling'
    registry = modeling/'active_prediction_model.json'
    if not registry.exists():
        return False
    config = json.loads(registry.read_text(encoding='utf-8'))
    if not isinstance(config,dict):
        raise ValueError('Registry mô hình phải là đối tượng JSON.')
    if config.get('forecast_pipeline') != PIPELINE_VERSION:
        return False
    if config.get('mode') != 'direct_forecast':
        raise ValueError('Chế độ mô hình đã sửa không hợp lệ.')
    latest = publish_active_snapshots(modeling)
    snapshot = latest['3']['snapshot_date']
    from .run_rolling_paper_trading import build_ledger_and_summary
    build_ledger_and_summary(modeling/'snapshot_forecasts.csv',lake/'domestic_gold_quotes.csv',
        modeling/'paper_trading_ledger.csv',modeling/'paper_trading_summary.json',after=snapshot)
    from scripts.build_web_data import main as build_dashboard
    build_dashboard()
    return True
