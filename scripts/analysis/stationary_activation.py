"""Chọn mô hình đã khóa riêng cho từng kỳ hạn làm dự báo mặc định."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

from .run_model_research import write_json
from .stationary_shadow import read_lock, record_latest, shadow_root

ACTIVATION_FILE = 'active_prediction_model.json'


def activate_candidate(modeling: Path, *, horizons=(3,)) -> dict:
    """Kích hoạt tuyến hiển thị, không sửa thuật toán/bản khóa hoặc cấp validated.

    File nằm trong dữ liệu modeling thay vì configs thuật toán: chọn dùng
    một mô hình đã khóa không làm thay đổi phương pháp của campaign đó.
    """
    entries = {}
    for horizon in horizons:
        lock = read_lock(shadow_root(modeling, horizon))
        if lock.get('horizon_months', horizon) != horizon:
            raise ValueError('Bản khóa không đúng kỳ hạn kích hoạt.')
        entries[str(horizon)] = dict(mode='direct_forecast', horizon_months=horizon, candidate=lock['candidate'],
                  protocol_id=lock['protocol_id'], source_id=lock['source_id'], margin=lock['margin'],
                  activated_at=datetime.now(timezone.utc).isoformat())
    if not entries:
        raise ValueError('Cần ít nhất một kỳ hạn kích hoạt.')
    # Đọc được cấu hình 3 tháng cũ; nhiều kỳ hạn dùng registry và ghi một lần
    # để giao diện không nhìn thấy trạng thái chỉ mới kích hoạt một phần.
    config = entries['3'] if tuple(horizons) == (3,) else dict(mode='direct_forecast', horizons=entries)
    temporary = modeling/(ACTIVATION_FILE+'.tmp')
    write_json(temporary, config)
    temporary.replace(modeling/ACTIVATION_FILE)
    return config


def load_active_forecast(modeling: Path, expected_date: str, *, horizon=3) -> dict:
    """Làm mới dự báo từ bản khóa rồi đối chiếu ngày, giá và campaign đang chọn.

    Lỗi phải lộ ra cho caller chuyển Quan sát; không âm thầm quay về mô hình
    cũ hoặc ghép xác suất/Q10 cũ vào dự báo điểm mới. Bản ghi độc lập vẫn do
    collector quản lý và giữ bản đầu tiên trong ngày như trước khi kích hoạt.
    """
    config = json.loads((modeling/ACTIVATION_FILE).read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('Cấu hình kích hoạt không đúng định dạng.')
    if 'horizons' in config:
        # Tệp cấu hình có thể bị sửa tay; báo lỗi nghiệp vụ thay vì làm sập
        # toàn bộ dashboard khi một entry không còn là đối tượng JSON.
        entries = config['horizons']
        if config.get('mode') != 'direct_forecast' or not isinstance(entries, dict):
            raise ValueError('Danh sách mô hình theo kỳ hạn không hợp lệ.')
        config = entries.get(str(horizon))
        if not isinstance(config, dict):
            raise ValueError('Cấu hình mô hình của kỳ hạn không hợp lệ.')
    root = shadow_root(modeling, horizon)
    lock = read_lock(root)
    if (config.get('horizon_months') != horizon or config.get('mode') != 'direct_forecast'
            or any(config.get(key) != lock.get(key) for key in ('candidate','protocol_id','source_id','margin'))):
        raise ValueError('Mô hình được chọn không khớp bản khóa đang theo dõi.')
    record_latest(modeling, horizon=horizon)
    latest = json.loads((root/'latest.json').read_text(encoding='utf-8'))
    if not isinstance(latest, dict) or not isinstance(latest.get('validation'), dict):
        raise ValueError('Dự báo mô hình mới không đúng định dạng.')
    validation = latest.get('validation', {})
    if (latest.get('snapshot_date') != expected_date or latest.get('horizon_months') != horizon
            or latest.get('candidate') != config['candidate'] or latest.get('margin') != config['margin']
            or validation.get('protocol_id') != config['protocol_id']):
        raise ValueError('Dự báo mô hình mới chưa khớp ngày dữ liệu hoặc giao thức.')
    for key in ('predicted_net_return','entry_sell_price'):
        if not math.isfinite(float(latest[key])):
            raise ValueError('Dự báo mô hình mới chứa số không hợp lệ.')
    if float(latest['entry_sell_price']) <= 0 or float(latest['predicted_net_return']) <= -1:
        raise ValueError('Giá/lợi suất mô hình mới không hợp lệ.')
    for key in ('q10_predicted_net_return','prob_return_positive'):
        value = latest.get(key)
        if value is not None and not math.isfinite(float(value)):
            raise ValueError('Chỉ số dự báo mô hình mới không hữu hạn.')
    probability = latest.get('prob_return_positive')
    if probability is not None and not 0 <= float(probability) <= 1:
        raise ValueError('Xác suất mô hình mới không hợp lệ.')
    return {**latest, 'validation_policy': lock.get('policy', {})}
