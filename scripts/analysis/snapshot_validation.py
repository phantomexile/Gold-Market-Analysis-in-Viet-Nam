"""Khóa quy tắc, lưu dự báo tiến cứu và tự động kiểm định từng kỳ hạn tháng lịch."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
LOCAL_TIMEZONE = timezone(timedelta(hours=7))
REQUIRED_CHECKS = (
    'inputs_verified', 'enough_rows', 'enough_time_span', 'enough_nonoverlap',
    'mae_vs_zero', 'brier_vs_baseline', 'q10_coverage', 'q10_pinball_vs_baseline', 'probability_calibration',
)


def load_policy() -> dict:
    """Đọc các ngưỡng cố định của dự án; đổi ngưỡng sẽ mở đợt kiểm định mới."""
    return json.loads((ROOT / 'configs' / 'forecast_validation_policy.json').read_text(encoding='utf-8'))


def _checksum(payload: dict) -> str:
    """Phát hiện tệp bị sửa/hỏng ngoài luồng; đây không phải chữ ký chống giả mạo."""
    body = {key: value for key, value in payload.items() if key != 'checksum'}
    return sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def model_source_fingerprint() -> str:
    """Đổi mã đặc trưng, nhãn, thuật toán hoặc thư viện thì không kế thừa thành tích cũ.

    Trọng số được phép học lại mỗi ngày theo cùng thuật toán đã khóa. Giao
    thức kiểm định quy trình tái huấn luyện này, không chỉ một bộ trọng số.
    """
    # Bao gồm cả phần thu thập/chuẩn hóa đầu vào và entrypoint, không chỉ estimator.
    # Việc đổi quy tắc premium hoặc availability cũng làm đợt kiểm định bắt đầu lại.
    paths = {ROOT / name for name in (
        'scripts/analysis/train_latest_snapshot.py', 'scripts/analysis/snapshot_calibration.py',
        'scripts/analysis/active_snapshot.py',
        'scripts/analysis/snapshot_validation.py', 'scripts/pipeline/refresh_latest_forecast.py',
        'scripts/analysis/snapshot_historical.py',
        'scripts/pipeline/update_incremental.py',
    )}
    for folder in ('src/gold_collectors', 'scripts/collection', 'scripts/processing'):
        paths.update((ROOT / folder).rglob('*.py'))
    paths.update((ROOT / 'configs').rglob('*.json'))
    digest = sha256()
    for path in sorted(paths):
        name = path.relative_to(ROOT).as_posix()
        digest.update(name.encode('utf-8'))
        digest.update(path.read_bytes())
    for package in ('numpy', 'pandas', 'scikit-learn', 'scipy', 'joblib'):
        try:
            installed = version(package)
        except PackageNotFoundError:
            installed = 'missing'
        digest.update(f'{package}={installed}'.encode('utf-8'))
    return digest.hexdigest()


def ensure_protocol(root: Path, source_id: str, *, now: datetime, policy: dict | None = None) -> dict:
    """Khóa giao thức trước ngày đánh giá; lần chạy sau dùng lại đúng quy tắc đã khóa."""
    if now.tzinfo is None:
        raise ValueError('Ngày khóa phải có múi giờ rõ ràng.')
    policy = policy or load_policy()
    protocol_id = _checksum({'source_id': source_id, 'policy': policy})[:24]
    folder = root / protocol_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'protocol.json'
    if not path.exists():
        protocol = {
            'protocol_id': protocol_id, 'source_id': source_id, 'policy': policy,
            'created_at': now.isoformat(),
            # Không hợp thức hóa dữ liệu đã xem; chỉ thu bằng chứng từ ngày kế tiếp.
            'validation_start': (now.astimezone(LOCAL_TIMEZONE).date() + timedelta(days=1)).isoformat(),
        }
        protocol['checksum'] = _checksum(protocol)
        try:
            with path.open('x', encoding='utf-8') as handle:
                json.dump(protocol, handle, ensure_ascii=False, indent=2, allow_nan=False)
        except FileExistsError:
            pass
    protocol = json.loads(path.read_text(encoding='utf-8'))
    created = datetime.fromisoformat(protocol['created_at'])
    if (protocol.get('checksum') != _checksum(protocol) or protocol.get('source_id') != source_id
            or protocol.get('policy') != policy or protocol.get('protocol_id') != protocol_id
            or created.tzinfo is None or created > now
            or date.fromisoformat(protocol['validation_start']) <= created.astimezone(LOCAL_TIMEZONE).date()):
        raise ValueError('Giao thức kiểm định bị sửa, sai ngày khóa hoặc không khớp cấu hình.')
    return protocol


def _check_forecast(row: dict) -> None:
    """Chỉ chấp nhận dự báo đầy đủ và baseline đã biết tại lúc phát tín hiệu."""
    if int(row['horizon_months']) not in (1, 3, 5):
        raise ValueError('Kỳ hạn kiểm định không hợp lệ.')
    date.fromisoformat(row['snapshot_date'])
    for name in ('predicted_net_return', 'q10_predicted_net_return', 'prob_return_positive',
                 'baseline_probability', 'baseline_q10', 'entry_sell_price'):
        if not math.isfinite(float(row[name])):
            raise ValueError(f'Số liệu kiểm định không hữu hạn: {name}.')
    if not 0 <= float(row['prob_return_positive']) <= 1 or not 0 <= float(row['baseline_probability']) <= 1:
        raise ValueError('Xác suất kiểm định nằm ngoài khoảng 0 đến 1.')
    if float(row['entry_sell_price']) <= 0:
        raise ValueError('Giá bán khi phát dự báo phải dương.')
    if row.get('probability_method') != 'temporal_oos_empirical_laplace' or int(row.get('calibration_rows', 0)) < 60:
        raise ValueError('Dự báo chưa đủ hiệu chỉnh xác suất ngoài mẫu.')


def record_forecasts(root: Path, protocol: dict, forecasts: list[dict], *, now: datetime) -> None:
    """Giữ bản phát đầu tiên trong ngày, tuyệt đối không thay dự báo sau khi biết kết quả."""
    today = now.astimezone(LOCAL_TIMEZONE).date().isoformat()
    folder = root / protocol['protocol_id'] / 'forecasts'
    folder.mkdir(parents=True, exist_ok=True)
    # Đối chiếu danh mục trước khi ghi để không tự hợp thức hóa tệp vừa bị xóa.
    read_journal(root, protocol)
    index_path = folder.parent / 'journal_index.json'
    index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {'files': {}}
    for forecast in forecasts:
        origin = forecast['snapshot_date']
        # Snapshot cũ hoặc trước ngày khóa vẫn được hiển thị, nhưng không thành bằng chứng độc lập.
        if origin != today or origin < protocol['validation_start']:
            continue
        _check_forecast(forecast)
        record = {**forecast, 'recorded_at': now.isoformat(), 'protocol_id': protocol['protocol_id']}
        record['checksum'] = _checksum(record)
        path = folder / f"{origin}-{int(record['horizon_months'])}m.json"
        try:
            with path.open('x', encoding='utf-8') as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2, allow_nan=False)
        except FileExistsError:
            # Chạy lại cùng ngày không được làm kết quả lịch sử đẹp hơn bằng dự báo mới.
            continue
        index['files'][path.name] = record['checksum']
        index['checksum'] = _checksum(index)
        temporary = index_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(index_path)


def read_journal(root: Path, protocol: dict) -> list[dict]:
    """Đọc bằng chứng cùng giao thức; tệp sai thời gian hoặc bị sửa làm đợt kiểm định thất bại."""
    records = []
    folder = root / protocol['protocol_id']
    paths = sorted((folder / 'forecasts').glob('*.json'))
    index_path = folder / 'journal_index.json'
    index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {'files': {}}
    if (set(index['files']) != {path.name for path in paths}
            or (index_path.exists() and index.get('checksum') != _checksum(index))):
        raise ValueError('Danh mục nhật ký không khớp: có dự báo bị mất, thêm hoặc sửa ngoài luồng.')
    for path in paths:
        record = json.loads(path.read_text(encoding='utf-8'))
        _check_forecast(record)
        recorded = datetime.fromisoformat(record['recorded_at'])
        if (record.get('checksum') != _checksum(record) or index['files'][path.name] != record.get('checksum')
                or record.get('protocol_id') != protocol['protocol_id']
                or recorded.tzinfo is None or recorded < datetime.fromisoformat(protocol['created_at'])
                or recorded.astimezone(LOCAL_TIMEZONE).date().isoformat() != record['snapshot_date']
                or record['snapshot_date'] < protocol['validation_start']
                or path.name != f"{record['snapshot_date']}-{int(record['horizon_months'])}m.json"):
            raise ValueError('Nhật ký dự báo bị sửa hoặc chứa bằng chứng không hợp lệ.')
        records.append(record)
    return records


def matured_forecasts(records: list[dict], prices: pd.DataFrame, *, as_of: str) -> list[dict]:
    """Ghép giá mua SJC đầu tiên từ ngày tròn tháng, giữ nguyên giá vào đã lưu."""
    curve = prices[['date', 'buy_price', 'sell_price']].copy()
    curve['date'] = pd.to_datetime(curve['date'], errors='coerce')
    curve['buy_price'] = pd.to_numeric(curve['buy_price'], errors='coerce')
    curve['sell_price'] = pd.to_numeric(curve['sell_price'], errors='coerce')
    curve = curve.loc[(curve['date'] <= pd.Timestamp(as_of)) & (curve['buy_price'] > 0)
                      & np.isfinite(curve['buy_price']) & (curve['sell_price'] >= curve['buy_price'])]
    curve = curve.sort_values('date').drop_duplicates('date')
    result = []
    for record in records:
        target = pd.Timestamp(record['snapshot_date']) + pd.DateOffset(months=int(record['horizon_months']))
        exits = curve.loc[curve['date'] >= target]
        if exits.empty:
            continue
        exit_row = exits.iloc[0]
        result.append({**record, 'exit_date': exit_row['date'].date().isoformat(),
                       'actual': float(exit_row['buy_price']) / float(record['entry_sell_price']) - 1})
    return result


def evaluate_horizon(rows: list[dict], horizon: int, policy: dict, *, blockers: list[str] | None = None) -> dict:
    """Tự cấp validated chỉ khi đủ bằng chứng và vượt mọi tiêu chí cố định của dự án."""
    blockers = list(blockers or [])
    rows = sorted((row for row in rows if int(row['horizon_months']) == horizon), key=lambda row: row['snapshot_date'])
    metrics: dict[str, Any] = {'matured_rows': len(rows), 'nonoverlapping_windows': 0, 'origin_span_days': 0}
    if rows:
        names = ['actual', 'predicted_net_return', 'q10_predicted_net_return',
                 'prob_return_positive', 'baseline_probability', 'baseline_q10']
        values = np.array([[float(row[name]) for name in names] for row in rows])
        if not np.isfinite(values).all() or not ((values[:, 3:5] >= 0) & (values[:, 3:5] <= 1)).all():
            return {'horizon_months': horizon, 'status': 'validation_failed', 'metrics': metrics,
                    'checks': {'valid_numbers': False}, 'reasons': ['Bằng chứng kiểm định chứa số liệu không hợp lệ.']}
        actual, predicted, q10, probability, baseline_p, baseline_q = values.T
        positive = (actual > 0).astype(float)
        error, base_error = actual - q10, actual - baseline_q
        # Pinball đo cả mức bao phủ lẫn độ sắc của Q10; Q10 quá thấp không được coi là tốt.
        pinball = np.maximum(0.1 * error, -0.9 * error)
        baseline_pinball = np.maximum(0.1 * base_error, -0.9 * base_error)
        # ECE chia xác suất thành các nhóm (ví dụ 70–80%) rồi đối chiếu với
        # tỷ lệ lãi thực tế của nhóm; nhóm có nhiều dự báo mang trọng số lớn hơn.
        ece = 0.0
        bins = np.minimum((probability * policy['probability_bins']).astype(int), policy['probability_bins'] - 1)
        for index in range(policy['probability_bins']):
            mask = bins == index
            if mask.any():
                ece += float(mask.mean() * abs(positive[mask].mean() - probability[mask].mean()))
        next_origin = pd.Timestamp.min
        # Các dự báo 5 tháng phát liên tiếp chia sẻ phần lớn giai đoạn nắm giữ.
        # Chỉ đếm thêm chu kỳ độc lập khi ngày vào mới không sớm hơn ngày thoát cũ.
        for row in rows:
            if pd.Timestamp(row['snapshot_date']) >= next_origin:
                metrics['nonoverlapping_windows'] += 1
                next_origin = pd.Timestamp(row['exit_date'])
        # Brier là bình phương sai số giữa xác suất lãi và kết quả 0/1;
        # càng nhỏ càng tốt. Baseline dùng tỷ lệ lãi của train đã lưu tại origin.
        metrics.update({
            'origin_span_days': (pd.Timestamp(rows[-1]['snapshot_date']) - pd.Timestamp(rows[0]['snapshot_date'])).days,
            'mae': float(np.abs(actual - predicted).mean()), 'zero_baseline_mae': float(np.abs(actual).mean()),
            'brier': float(np.square(probability - positive).mean()),
            'baseline_brier': float(np.square(baseline_p - positive).mean()),
            'q10_breach_rate': float((actual < q10).mean()), 'q10_pinball': float(pinball.mean()),
            'baseline_q10_pinball': float(baseline_pinball.mean()), 'probability_ece': ece,
        })
        for row in rows:
            blockers.extend(row.get('input_blockers', []))
    checks = {
        'inputs_verified': not blockers,
        'enough_rows': len(rows) >= policy['min_matured_rows'],
        'enough_time_span': metrics['origin_span_days'] >= policy['min_origin_span_days'],
        'enough_nonoverlap': metrics['nonoverlapping_windows'] >= policy['min_nonoverlapping_windows'],
        'mae_vs_zero': bool(rows) and metrics['zero_baseline_mae'] > 0 and metrics['mae'] <= (1 - policy['min_mae_improvement']) * metrics['zero_baseline_mae'],
        'brier_vs_baseline': bool(rows) and metrics['baseline_brier'] > 0 and metrics['brier'] <= (1 - policy['min_brier_improvement']) * metrics['baseline_brier'],
        'q10_coverage': bool(rows) and metrics['q10_breach_rate'] <= policy['max_q10_breach_rate'],
        'q10_pinball_vs_baseline': bool(rows) and metrics['q10_pinball'] <= metrics['baseline_q10_pinball'],
        'probability_calibration': bool(rows) and metrics['probability_ece'] <= policy['max_probability_ece'],
    }
    messages = {
        'enough_rows': f"Chưa đủ {policy['min_matured_rows']} dự báo mới đã đáo hạn.",
        'enough_time_span': f"Chưa đủ {policy['min_origin_span_days']} ngày phát dự báo độc lập.",
        'enough_nonoverlap': f"Chưa đủ {policy['min_nonoverlapping_windows']} cửa sổ lợi suất không chồng lấn.",
        'mae_vs_zero': 'Sai số MAE chưa tốt hơn baseline lợi suất 0 theo ngưỡng đã khóa.',
        'brier_vs_baseline': 'Brier của xác suất chưa tốt hơn baseline theo ngưỡng đã khóa.',
        'q10_coverage': 'Tỷ lệ lợi suất xuyên Q10 vượt ngưỡng cho phép.',
        'q10_pinball_vs_baseline': 'Pinball của Q10 kém hơn baseline.',
        'probability_calibration': 'Sai lệch hiệu chỉnh xác suất vượt ngưỡng cho phép.',
    }
    enough = all(checks[key] for key in ('enough_rows', 'enough_time_span', 'enough_nonoverlap'))
    status = 'validation_failed' if blockers else ('validation_pending' if not enough else
                                                  ('validated' if all(checks.values()) else 'validation_failed'))
    reasons = list(dict.fromkeys(blockers))
    for key, message in messages.items():
        if not checks[key] and (enough or key.startswith('enough_')):
            reasons.append(message)
    return {'horizon_months': horizon, 'status': status, 'metrics': metrics, 'checks': checks, 'reasons': reasons}


def input_availability_blockers(frame: pd.DataFrame, candidates: list[str], lake: Path) -> list[str]:
    """Chặn cấp trạng thái khi nguồn tin/sự kiện chưa chứng minh khả dụng tại ngày dự báo."""
    diagnostics = frame.attrs.get('diagnostics', {})
    blockers = []
    if any(name.startswith(('raw_news_', 'news_sentiment_')) for name in candidates) and diagnostics.get('raw_news_availability_verified') is not True:
        blockers.append('Tin lịch sử hồi cứu chưa được xác minh thời điểm khả dụng.')
    from gold_collectors.modeling.config import ModelingConfig
    from gold_collectors.modeling.features import _event_path
    # Dùng đúng thứ tự fallback của builder, tránh kiểm tra một tệp nhưng học tệp khác.
    events_path = _event_path(ModelingConfig(data_lake=lake))
    # Builder đã lọc trước khi sinh đặc trưng thì proxy còn trong kho chỉ dùng
    # để hiển thị tin, không được coi là blocker của mô hình đã loại chúng.
    if events_path.exists() and diagnostics.get('event_availability_verified') is not True:
        events = pd.read_csv(events_path, usecols=lambda name: name == 'source')
        if 'source' not in events or events['source'].isna().any():
            blockers.append('Nguồn sự kiện thiếu thông tin xuất xứ để xác minh thời điểm khả dụng.')
        elif (events['source'].eq('google_news_rss_event_proxy').any()
              and diagnostics.get('event_availability_verified') is not True):
            blockers.append('Sự kiện proxy RSS chưa được xác minh thời điểm khả dụng cho mô hình.')
    return blockers


def apply_validation_results(forecasts: list[dict], report: dict) -> None:
    """Cập nhật trạng thái và cờ mua từ báo cáo mới; thiếu/sai báo cáo thì đóng cổng mua."""
    details = {item['horizon_months']: item for item in report['horizons']}
    for forecast in forecasts:
        detail = details.get(int(forecast['horizon_months']))
        matches = (forecast['snapshot_date'] == report.get('snapshot_date') and bool(report.get('protocol_id')))
        if detail is None or not matches:
            status, reasons = 'validation_failed', ['Báo cáo kiểm định không khớp snapshot hoặc kỳ hạn.']
        else:
            status, reasons = detail['status'], list(detail['reasons'])
            checks = detail.get('checks')
            if status == 'validated' and (not isinstance(checks, dict)
                                          or not all(checks.get(name) is True for name in REQUIRED_CHECKS)):
                status, reasons = 'validation_failed', ['Báo cáo chưa vượt qua đầy đủ các tiêu chí kiểm định.']
        try:
            _check_forecast(forecast)
        except (ValueError, TypeError, KeyError) as exc:
            status, reasons = 'validation_failed', [f'Dự báo hiện tại không đủ điều kiện: {exc}']
        forecast.update({
            'status': status, 'validation_protocol_id': report.get('protocol_id', ''),
            'validation_reason': 'Đạt đầy đủ tiêu chí kiểm định đã khóa.' if status == 'validated' else ' '.join(reasons),
            'buy_signal': bool(status == 'validated' and float(forecast['prob_return_positive']) >= 0.5
                               and float(forecast['q10_predicted_net_return']) >= -0.1),
        })


def run_validation(
    modeling_dir: Path, forecasts: list[dict], prices: pd.DataFrame,
    *, source_id: str, blockers: list[str], now: datetime | None = None,
) -> dict:
    """Bước tự động sau huấn luyện: ghi dự báo, cập nhật đánh giá và xuất báo cáo cùng ngày."""
    now = now or datetime.now(timezone.utc)
    root = modeling_dir / 'validation'
    policy = load_policy()
    snapshot_date = forecasts[0]['snapshot_date']
    protocol_id, start, matured = '', '', []
    errors = list(blockers)
    try:
        protocol = ensure_protocol(root, source_id, now=now, policy=policy)
        protocol_id, start = protocol['protocol_id'], protocol['validation_start']
        # Trạng thái/cờ mua không phải đầu vào kiểm định; chỉ lưu số liệu dự báo và baseline.
        journal_rows = [{**row, 'input_blockers': blockers} for row in forecasts]
        record_forecasts(root, protocol, journal_rows, now=now)
        matured = matured_forecasts(read_journal(root, protocol), prices, as_of=snapshot_date)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        errors.append(f'Không thể xác minh bằng chứng kiểm định: {exc}')
    report = {
        'generated_at': now.isoformat(), 'snapshot_date': snapshot_date,
        'protocol_id': protocol_id, 'validation_start': start, 'policy': policy,
        'horizons': [evaluate_horizon(matured, horizon, policy, blockers=errors) for horizon in (1, 3, 5)],
    }
    path = modeling_dir / 'snapshot_validation_report.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)
    return report
