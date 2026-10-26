"""Khóa từng kỳ hạn và tích lũy bằng chứng mới riêng cho mô hình cải tiến."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256
import importlib.metadata
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .run_model_research import file_hash, write_json
from .snapshot_validation import _checksum, matured_forecasts, evaluate_horizon, load_policy, model_source_fingerprint
from .stationary_features import build_stationary_features
from .stationary_research import fit_predict, calibrate, KINDS
from .forecast_signals import direct_signal

ROOT = Path(__file__).resolve().parents[2]
LOCAL = timezone(timedelta(hours=7))


def shadow_root(modeling: Path, horizon: int = 3) -> Path:
    """Tách nhật ký theo kỳ hạn; giữ đường dẫn 3 tháng để đọc bản khóa cũ."""
    if horizon not in (1, 3, 5):
        raise ValueError('Kỳ hạn phải là 1, 3 hoặc 5 tháng.')
    root = modeling/'stationary_shadow'
    return root if horizon == 3 else root/f'{horizon}m'


def algorithm_fingerprint() -> str:
    """Đóng dấu thuật toán, quy tắc tín hiệu và thư viện; dữ liệu mới được phép tăng."""
    digest = sha256()
    # Bao gồm cả maturity/scoring dùng chung, builder, collection/processing,
    # cấu hình và phiên bản thư viện; thay cách tạo đầu vào phải khóa đợt mới.
    digest.update(model_source_fingerprint().encode('utf-8'))
    for name in ('stationary_features.py', 'stationary_research.py', 'stationary_evaluation.py',
                 'stationary_shadow.py', 'run_stationary_research.py', 'forecast_signals.py',
                 'run_model_research.py', 'model_diagnostics.py', 'run_all_horizon_rf.py'):
        digest.update((ROOT/'scripts/analysis'/name).read_bytes())
    digest.update((ROOT/'configs/forecast_validation_policy.json').read_bytes())
    for package in ('numpy', 'pandas', 'scikit-learn', 'scipy', 'joblib'):
        digest.update(f'{package}={importlib.metadata.version(package)}'.encode())
    return digest.hexdigest()


def create_lock(root: Path, calibration: Path, *, candidate: str, margin: float,
                now: datetime, source_id: str | None = None, horizon=3) -> dict:
    """Chụp bộ OOS ban đầu, khóa cấu hình và bắt đầu bằng chứng từ ngày kế tiếp."""
    if horizon not in (1, 3, 5) or now.tzinfo is None or candidate not in KINDS or margin not in (.005, .01, .02):
        raise ValueError('Cấu hình khóa không hợp lệ.')
    config = dict(candidate=candidate, margin=margin, source_id=source_id or algorithm_fingerprint(),
                  initial_calibration_sha256=file_hash(calibration), horizon_months=horizon,
                  refit='monthly_5y_matured_only', calibration='sigmoid_oos_24m_residual_q10', policy=load_policy())
    identity = _checksum(config)[:24]
    folder = root/identity
    folder.mkdir(parents=True, exist_ok=True)
    protocol = {**config, 'protocol_id': identity, 'created_at': now.isoformat(),
                'validation_start': (now.astimezone(LOCAL).date()+timedelta(days=1)).isoformat(), 'mode': 'shadow'}
    protocol['checksum'] = _checksum(protocol)
    if not (folder/'protocol.json').exists():
        with (folder/'calibration.csv').open('xb') as stream:
            stream.write(calibration.read_bytes())
        with (folder/'protocol.json').open('x', encoding='utf-8') as stream:
            json.dump(protocol, stream, ensure_ascii=False, allow_nan=False, indent=2)
    write_json(root/'active.json', {'protocol_id': identity})
    return read_lock(root, source_id=config['source_id'])


def read_lock(root: Path, *, source_id: str | None = None) -> dict:
    """Không tự tái khóa hoặc kế thừa thành tích khi mã hay dữ liệu hiệu chỉnh bị sửa."""
    identity = json.loads((root/'active.json').read_text(encoding='utf-8'))['protocol_id']
    if not isinstance(identity, str) or len(identity) != 24 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError('Đường dẫn giao thức không hợp lệ.')
    folder = root/identity
    protocol = json.loads((folder/'protocol.json').read_text(encoding='utf-8'))
    if (protocol.get('checksum') != _checksum(protocol) or protocol.get('protocol_id') != identity
            or protocol.get('source_id') != (source_id or algorithm_fingerprint())
            or protocol.get('initial_calibration_sha256') != file_hash(folder/'calibration.csv')):
        raise ValueError('Bản khóa không khớp mã hoặc dữ liệu hiệu chỉnh; cần một đợt mới.')
    return protocol


def read_records(root: Path, protocol: dict) -> list[dict]:
    """Đối chiếu chỉ mục để phát hiện cả tệp mất/thêm và nội dung bị sửa."""
    folder = root/protocol['protocol_id']
    paths = sorted((folder/'forecasts').glob('*.json'))
    index_file = folder/'journal_index.json'
    index = json.loads(index_file.read_text(encoding='utf-8')) if index_file.exists() else {'files': {}}
    if set(index['files']) != {p.name for p in paths} or (index_file.exists() and index.get('checksum') != _checksum(index)):
        raise ValueError('Nhật ký shadow mất/thêm hoặc sai chỉ mục.')
    result = []
    for path in paths:
        row = json.loads(path.read_text(encoding='utf-8'))
        when = datetime.fromisoformat(row['recorded_at'])
        if (row.get('checksum') != _checksum(row) or index['files'][path.name] != row['checksum']
                or row.get('protocol_id') != protocol['protocol_id'] or when.tzinfo is None
                or when < datetime.fromisoformat(protocol['created_at'])
                or when.astimezone(LOCAL).date().isoformat() != row['snapshot_date']
                or row['snapshot_date'] < protocol['validation_start']
                or row.get('horizon_months') != protocol['horizon_months']
                or path.name != f"{row['snapshot_date']}-{protocol['horizon_months']}m.json"):
            raise ValueError('Dự báo shadow không đúng bản ghi gốc hoặc thời điểm phát.')
        result.append(row)
    return result


def append_forecast(root: Path, protocol: dict, forecast: dict, *, now: datetime) -> None:
    """Chỉ ghi dự báo ngày hiện tại sau ngày bắt đầu; cùng ngày giữ bản đầu tiên."""
    read_records(root, protocol)
    if now.tzinfo is None:
        raise ValueError('Thời điểm ghi phải có múi giờ.')
    origin = forecast['snapshot_date']
    if origin != now.astimezone(LOCAL).date().isoformat() or origin < protocol['validation_start']:
        return
    for name in ('predicted_net_return', 'entry_sell_price', 'baseline_probability', 'baseline_q10'):
        if not math.isfinite(float(forecast[name])):
            raise ValueError(f'Dự báo shadow không hữu hạn: {name}')
    if float(forecast['entry_sell_price']) <= 0 or int(forecast['horizon_months']) != protocol['horizon_months']:
        raise ValueError('Giá/kỳ hạn shadow không hợp lệ.')
    for name in ('q10_predicted_net_return', 'prob_return_positive'):
        value = forecast.get(name)
        if value is not None and not math.isfinite(float(value)):
            raise ValueError(f'Số liệu shadow không hữu hạn: {name}')
    for name in ('baseline_probability', 'prob_return_positive'):
        value = forecast.get(name)
        if value is not None and not 0 <= float(value) <= 1:
            raise ValueError('Xác suất shadow phải nằm trong 0 đến 1.')
    folder = root/protocol['protocol_id']
    (folder/'forecasts').mkdir(exist_ok=True)
    row = {**forecast, 'protocol_id': protocol['protocol_id'], 'recorded_at': now.isoformat()}
    row['checksum'] = _checksum(row)
    path = folder/'forecasts'/f"{origin}-{protocol['horizon_months']}m.json"
    try:
        with path.open('x', encoding='utf-8') as stream:
            json.dump(row, stream, ensure_ascii=False, allow_nan=False, indent=2)
    except FileExistsError:
        return
    index_path = folder/'journal_index.json'
    index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {'files': {}}
    index['files'][path.name] = row['checksum']
    index['checksum'] = _checksum(index)
    temporary = index_path.with_suffix('.tmp')
    write_json(temporary, index)
    temporary.replace(index_path)


def record_latest(modeling: Path, *, now: datetime | None = None, horizon=3) -> dict | None:
    """Hook cập nhật: fit đúng lịch đã khóa, ghi shadow riêng và chấm khi đáo hạn."""
    root = shadow_root(modeling, horizon)
    if not (root/'active.json').exists():
        return None
    now = now or datetime.now(timezone.utc)
    protocol = read_lock(root)
    if protocol['horizon_months'] != horizon:
        raise ValueError('Bản khóa không đúng kỳ hạn yêu cầu.')
    target, exit_column = f'net_return_{horizon}m', f'exit_date_{horizon}m'
    frame_path = modeling/'model_frame_daily.csv'
    before = file_hash(frame_path)
    f = pd.read_csv(frame_path, low_memory=False).sort_values('date').reset_index(drop=True)
    f['date'] = pd.to_datetime(f.date)
    f[exit_column] = pd.to_datetime(f[exit_column], errors='coerce')
    x = build_stationary_features(f)
    latest = f.iloc[[-1]]
    origin = latest.date.iloc[0]
    if origin.date() > now.astimezone(LOCAL).date():
        raise ValueError('Frame chứa ngày tương lai so với lúc phát dự báo.')
    begin = origin.to_period('M').start_time
    train_mask = f.date.ge(begin-pd.DateOffset(years=5)) & f[exit_column].lt(begin) & f.date.lt(begin) & np.isfinite(f[target])
    train = f.loc[train_mask]
    if len(train) < 300:
        raise ValueError('Thiếu train cho ứng viên đã khóa.')
    predicted, selected = fit_predict(protocol['candidate'], train, latest, x.loc[train_mask], x.iloc[[-1]], horizon=horizon)
    initial = pd.read_csv(root/protocol['protocol_id']/'calibration.csv', low_memory=False)
    if 'horizon_months' in initial and not initial.horizon_months.eq(horizon).all():
        raise ValueError('Bộ hiệu chỉnh không đúng kỳ hạn của bản khóa.')
    initial_records = [dict(snapshot_date=str(r.date)[:10], horizon_months=horizon, entry_sell_price=r.sell_price,
                            predicted_net_return=r.predicted) for r in initial.itertuples()]
    journal = read_records(root, protocol)
    matured = matured_forecasts(journal, f, as_of=origin.date().isoformat())
    pool = matured_forecasts(initial_records, f, as_of=origin.date().isoformat()) + matured
    past = pd.DataFrame([dict(date=pd.Timestamp(r['snapshot_date']), exit_date=pd.Timestamp(r['exit_date']),
                              actual=r['actual'], predicted=r['predicted_net_return']) for r in pool])
    if not past.empty:
        past = past.drop_duplicates('date').loc[lambda p: p.exit_date.lt(begin) & p.date.ge(begin-pd.DateOffset(years=2))]
    calibrated = calibrate(past, predicted)
    finite = lambda value: float(value) if np.isfinite(value) else None
    row = dict(snapshot_date=origin.date().isoformat(), horizon_months=horizon, candidate=protocol['candidate'],
               predicted_net_return=float(predicted[0]), q10_predicted_net_return=finite(calibrated['q10'][0]),
               prob_return_positive=finite(calibrated['probability'][0]), entry_sell_price=float(latest.sell_price.iloc[0]),
               baseline_probability=float((train[target]>0).mean()), baseline_q10=float(train[target].quantile(.1)),
               train_last_exit_date=str(train[exit_column].max().date()), calibration_rows=calibrated['rows'],
               calibration_last_exit_date=str(calibrated['last_exit'].date()) if pd.notna(calibrated['last_exit']) else None,
               selected_features=selected, margin=protocol['margin'], probability_method='sigmoid_temporal_oos',
               signal=direct_signal(predicted[0], latest.buy_price.iloc[0], latest.sell_price.iloc[0], margin=protocol['margin'])['signal'])
    if file_hash(frame_path) != before:
        raise ValueError('Frame thay đổi trong lúc fit shadow; chưa ghi dự báo.')
    # Mã hoặc bộ hiệu chỉnh có thể đổi ngay trong lúc fit: đối chiếu lại
    # trước khi ghi, không chỉ kiểm tra hash ở đầu bước xử lý.
    read_lock(root)
    append_forecast(root, protocol, row, now=now)
    # Chỉ báo cáo điểm đủ P/Q10; số dự báo điểm ghi được vẫn được báo riêng.
    records = read_records(root, protocol)
    matured = matured_forecasts(records, f, as_of=origin.date().isoformat())
    evaluable = [r for r in matured if r['q10_predicted_net_return'] is not None and r['prob_return_positive'] is not None]
    report = evaluate_horizon(evaluable, horizon, protocol['policy'])
    report.update(mode='shadow', protocol_id=protocol['protocol_id'], validation_start=protocol['validation_start'],
                  recorded_rows=len(records), matured_point_rows=len(matured))
    write_json(root/'latest.json', {**row, 'mode': 'shadow', 'validation': report,
                                  'eligible_for_prospective': any(r['snapshot_date'] == row['snapshot_date'] for r in records)})
    return report
