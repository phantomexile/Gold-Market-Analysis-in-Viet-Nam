"""Chạy nghiên cứu bước 1–3 và xuất bằng chứng riêng, không cập nhật dashboard."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

from scripts.analysis.model_diagnostics import audit_targets, diagnose_history
from scripts.analysis.model_research import candidates, run_monthly, select_annual, summarize_research


def write_json(path: Path, value: dict | list) -> None:
    """JSON nghiêm ngặt, UTF-8 không BOM; lỗi số NaN phải lộ ra thay vì ghi file sai."""
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    path.write_text(content + '\n', encoding='utf-8')


def prepare_output(folder: Path, manifest: dict) -> None:
    """Mỗi lần chạy có thư mục mới; không thay bằng chứng của lần chạy trước."""
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / 'manifest.json', manifest)


def file_hash(path: Path) -> str:
    """Hash gắn báo cáo với đúng bản dữ liệu/mã, không phải chứng thư nguồn dữ liệu."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def resolve_features(frame: pd.DataFrame) -> list[str]:
    """Lấy schema từ builder hiện tại; file feature_columns cũ còn kỳ hạn 21/63/105.

    Chỉ dựng lại tên đặc trưng trên các cột gốc để tránh nhân đôi cột phái
    sinh đã lưu. Giá trị dùng fit vẫn là frame đã chụp, không tự ghép lại
    lake có thể khác phiên bản. Thiếu cột theo schema mới thì dừng rõ lỗi.
    """
    from gold_collectors.modeling import ModelingConfig
    from gold_collectors.modeling.features import _add_lagged_features
    base = frame[[name for name in frame if '_lag_' not in name and '_roll_' not in name]].copy()
    _, names = _add_lagged_features(base, ModelingConfig())
    missing = [name for name in names if name not in frame]
    if missing:
        raise ValueError(f'Frame thiếu đặc trưng theo schema hiện tại: {missing}')
    return names


def _markdown(report: dict, audit: list, diagnostics: dict) -> str:
    """Xuất bản đọc nhanh; số liệu lợi suất đổi sang điểm phần trăm rõ đơn vị."""
    lines = ['# Kết quả nghiên cứu mô hình lợi suất', '',
             'Đây là sàng lọc trên lịch sử đã xem. Chưa đánh giá lại xác suất/Q10, chưa cấp validated và chưa thay mô hình vận hành.', '',
             'Huấn luyện đầu mỗi tháng, chỉ dùng nhãn đã đáo hạn trước tháng. Chọn cấu hình vào đầu năm bằng MAE bình quân tháng của 24 tháng trước đã đáo hạn, tối thiểu 6 tháng/120 dòng.', '',
             '## Tính nhất quán nhãn', '',
             '| Kỳ hạn | Nhãn sai lợi suất | Ngày thoát sai | Giá không hợp lệ |',
             '|---|---:|---:|---:|']
    for a in audit:
        lines.append(f"| {a['horizon_months']} tháng | {a['return_mismatches']} | {a['exit_mismatches']} | {a['invalid_price_rows']} |")
    lines += ['', 'Kiểm tra trên model frame, chưa đối chiếu độc lập từng báo giá nguồn.', '',
              '## Chẩn đoán mô hình đóng băng theo năm hiện tại', '',
              '| Kỳ hạn | MAE (điểm %) | Bias dự báo − thực tế (điểm %) |', '|---|---:|---:|']
    for d in diagnostics['by_horizon']:
        lines.append(f"| {d['horizon_months']} tháng | {d['mae']*100:.2f} | {d['bias']*100:+.2f} |")
    lines += ['', '## Đối chứng cùng lịch huấn luyện tháng', '',
              '| Kỳ hạn | Ứng viên | MAE (điểm %) | Cải thiện so với 0 |', '|---|---|---:|---:|']
    for h in (1, 3, 5):
        rows = sorted([r for r in report['candidates'] if r['horizon_months'] == h], key=lambda r: r['mae'])
        for r in rows:
            improvement = r['mae_improvement_vs_zero']
            text = f'{improvement*100:+.1f}%' if improvement is not None else 'không xác định'
            lines.append(f"| {h} tháng | {r['candidate']} | {r['mae']*100:.2f} | {text} |")
    lines += ['', 'Bảng trên đã xem toàn kỳ nghiên cứu, không dùng người thắng bảng này làm bằng chứng độc lập.', '',
              '## Chuỗi lựa chọn cấu hình trước từng năm', '',
              '| Kỳ hạn | MAE (điểm %) | Cải thiện so với 0 | Cửa sổ không chồng lấn |', '|---|---:|---:|---:|']
    for r in report['nested_selection']:
        improvement = r['mae_improvement_vs_zero']
        text = f'{improvement*100:+.1f}%' if improvement is not None else 'không xác định'
        lines.append(f"| {r['horizon_months']} tháng | {r['mae']*100:.2f} | {text} | {r['nonoverlapping_windows']} |")
    lines += ['', 'Chi tiết theo năm, nhóm đặc trưng, nhóm xác suất và tháng sai nhiều nằm trong các file JSON kèm theo.', '',
              'Chỉ số này chưa đủ kết luận mô hình đạt toàn bộ chất lượng: Brier, ECE, Q10 và bằng chứng tiến cứu vẫn phải kiểm tra riêng.', '']
    return '\n'.join(lines)


def main() -> None:
    """Khóa manifest trước khi fit; lỗi audit dừng thí nghiệm, không làm mới tín hiệu."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    modeling = ROOT / 'data/lake/modeling'
    research_root = modeling / 'research'
    folder = args.output or research_root / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = folder.resolve()
    if not folder.is_relative_to(research_root.resolve()) or folder == research_root.resolve():
        raise ValueError('Thư mục xuất phải nằm bên trong modeling/research để bảo vệ artifact vận hành.')
    inputs = [modeling / name for name in ('model_frame_daily.csv', 'feature_columns.json',
              'snapshot_historical_predictions.csv', 'snapshot_historical_report.json')]
    sources = [Path(__file__), ROOT / 'scripts/analysis/model_diagnostics.py',
               ROOT / 'scripts/analysis/model_research.py', ROOT / 'scripts/analysis/snapshot_calibration.py',
               ROOT / 'src/gold_collectors/modeling/features.py', ROOT / 'src/gold_collectors/modeling/config.py',
               ROOT / 'configs/forecast_validation_policy.json']
    watched = inputs + sources
    # Theo dõi các file nhạy cảm trước/sau nghiên cứu để chứng minh không ghi đè chúng.
    protected = [modeling / name for name in ('snapshot_forecasts.csv', 'snapshot_validation_report.json',
                 'paper_trading_ledger.csv')] + [ROOT / 'web/data/gold_dashboard_data.json']
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): file_hash(p) for p in watched + protected}
    registry = candidates()
    manifest = {'status': 'research_only', 'started_at': datetime.now(timezone.utc).isoformat(),
                'input_and_source_sha256': hashes,
                'versions': {name: importlib.metadata.version(name) for name in ('numpy', 'pandas', 'scikit-learn', 'scipy')},
                'candidate_registry': [asdict(s) for s in registry],
                'warmup_start': '2021-01-01', 'evaluation_start': '2023-01-01',
                'refit_frequency': 'monthly', 'selection_frequency': 'annual',
                'selection_lookback_months': 24, 'selection_min_months': 6, 'selection_min_rows': 120,
                'scope': 'approved_steps_1_to_3_point_forecasts_only'}
    prepare_output(folder, manifest)
    f = pd.read_csv(inputs[0], low_memory=False)
    f['date'] = pd.to_datetime(f.date)
    legacy_features = json.loads(inputs[1].read_text(encoding='utf-8'))
    features = resolve_features(f)
    write_json(folder / 'feature_columns.json', features)
    history = pd.read_csv(inputs[2], low_memory=False)
    existing_report = json.loads(inputs[3].read_text(encoding='utf-8'))
    if existing_report['snapshot_date'] != str(f.date.max().date()):
        raise ValueError('Báo cáo lịch sử và frame không cùng ngày snapshot.')
    audit = audit_targets(f)
    write_json(folder / 'target_audit.json', audit)
    if any(a['return_mismatches'] or a['exit_mismatches'] or a['invalid_price_rows'] for a in audit):
        raise ValueError('Nhãn/giá không nhất quán; xem target_audit.json trước khi huấn luyện.')
    diagnostics = diagnose_history(history, f)
    write_json(folder / 'historical_diagnostics.json', diagnostics)
    quality = {'rows': len(f), 'features': len(features), 'snapshot_date': str(f.date.max().date()),
               'duplicate_dates': int(f.date.duplicated().sum()),
               'legacy_manifest_missing_columns': [name for name in legacy_features if name not in f],
               'feature_schema_source': 'current_builder_same_as_snapshot_training',
               'missing_rate_by_feature': {name: float(pd.to_numeric(f[name], errors='coerce').replace([float('inf'), -float('inf')], float('nan')).isna().mean()) for name in features},
               'source_input_diagnostics': existing_report.get('input_diagnostics', {})}
    write_json(folder / 'input_quality.json', quality)
    outputs = []
    for horizon in (1, 3, 5):
        p = run_monthly(f, features, horizon, registry, progress=lambda message: print(message, flush=True))
        p.to_csv(folder / f'predictions_{horizon}m.csv', index=False, encoding='utf-8')
        outputs.append(p)
    predictions = pd.concat(outputs, ignore_index=True)
    selections = select_annual(predictions)
    write_json(folder / 'selections.json', selections)
    report = summarize_research(predictions, selections)
    report['snapshot_date'] = quality['snapshot_date']
    report['original_annual_metrics'] = diagnostics['by_horizon']
    if any(file_hash(p) != hashes[str(p.relative_to(ROOT)).replace('\\', '/')] for p in watched + protected):
        raise RuntimeError('Dữ liệu/mã/artifact thay đổi trong lúc chạy; không công nhận kết quả hoàn tất.')
    write_json(folder / 'report.json', report)
    (folder / 'report.md').write_text(_markdown(report, audit, diagnostics), encoding='utf-8')
    manifest['completed_at'] = datetime.now(timezone.utc).isoformat()
    manifest['protected_artifacts_unchanged'] = True
    manifest['snapshot_date'] = quality['snapshot_date']
    write_json(folder / 'manifest.json', manifest)
    print(f'Hoàn tất nghiên cứu: {folder}', flush=True)


if __name__ == '__main__':
    main()
