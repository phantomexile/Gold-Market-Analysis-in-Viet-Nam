"""So sánh LightGBM/CatBoost với RF đã khóa; chỉ xuất nghiên cứu, không kích hoạt."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
for path in (ROOT,ROOT/'src'):
    if str(path) not in sys.path:
        sys.path.insert(0,str(path))

from scripts.analysis.quantile_challengers import PARAMETERS,run_challengers,reference_intervals,interval_metrics
from scripts.analysis.stationary_evaluation import evaluate_candidate
from scripts.analysis.stationary_shadow import algorithm_fingerprint,read_lock
from scripts.analysis.run_model_research import file_hash,write_json,prepare_output
from scripts.analysis.model_diagnostics import audit_targets


def markdown(report: dict) -> str:
    """Giữ rõ point và native quantile là hai tiêu chí khác nhau khi so thuật toán."""
    lines=['# Đối chứng LightGBM Quantile và CatBoost MultiQuantile','',
           'Kỳ hạn ba tháng, cùng frame/34 đặc trưng/train5năm/refittháng/ngưỡng1%. Lịch sử đã xem để phát triển; không cấp validated hoặc đổi mô hình đang chạy.','',
           '| Mô hình | MAE (điểm %) | So zero | Brier | ECE (điểm %) | Xuyên Q10 |',
           '|---|---:|---:|---:|---:|---:|']
    for name,result in report['candidates'].items():
        m=result['quality']['metrics']
        lines.append(f"| {name} | {result['mae']*100:.2f} | {result['mae_improvement']*100:+.1f}% | {m['brier']:.3f} | {m['probability_ece']*100:.2f} | {m['q10_breach_rate']*100:.2f}% |")
    lines+=['','## Khoảng dự báo và danh mục','',
            '| Mô hình | Độ phủ Q10–Q90 | Độ rộng (điểm %) | Lợi suất toàn kỳ | Giảm tối đa | Đủ tiêu chí phát triển |',
            '|---|---:|---:|---:|---:|---|']
    for name,result in report['candidates'].items():
        q=report['intervals'][name];p=result['portfolio']
        lines.append(f"| {name} | {q['coverage']*100:.1f}% | {q['mean_width']*100:.2f} | {p['total_return']*100:+.1f}% | {p['max_drawdown']*100:.1f}% | {result['development_qualified']} |")
    lines+=['','Khoảng Q10–Q90 có mục tiêu độ phủ 80%; phải xét cả độ rộng và pinball, không chỉ đẩy khoảng rộng để đạt độ phủ.',
            'Lợi suất danh mục là toàn kỳ, đã tính spread, chưa tính các phí khác. Không phải lợi suất năm hoặc lợi suất tương lai.',
            'LightGBM/CatBoost lấy Q50 làm point và Q10 học trực tiếp; RF dùng point hồi quy và Q10 residual. Đây là so sánh toàn phương pháp, không tách riêng tác động họ thuật toán.',
            'P(lãi) dùng cùng sigmoid OOS24tháng. report.json có thêm Q10 residual cho hai ứng viên để đối chiếu cùng công thức RF.',
            'Không thử thêm cấu hình sau khi xem kết quả. Dashboard/active model/campaign giữ nguyên.','']
    return '\n'.join(lines)


def main():
    """Khóa cấu hình trước fit; đối chiếu dữ liệu/reference và artifact trước/sau."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    modeling=ROOT/'data/lake/modeling'
    research=modeling/'research'
    reference_folder=research/'2026-10-25-stationary-v2'
    output=(args.output or research/datetime.now(timezone.utc).strftime('quantile-%Y%m%dT%H%M%SZ')).resolve()
    if not output.is_relative_to(research.resolve()) or output==research.resolve():
        raise ValueError('Kết quả phải nằm trong modeling/research.')
    source_id=algorithm_fingerprint()
    reference_manifest=json.loads((reference_folder/'manifest.json').read_text(encoding='utf-8'))
    frame_path=modeling/'model_frame_daily.csv'
    if (source_id!=reference_manifest['source_id'] or file_hash(frame_path)!=reference_manifest['protected_sha256']['data/lake/modeling/model_frame_daily.csv']):
        raise ValueError('Frame/mã/corelibraries khác RF tham chiếu: cần tạo đối chứng cùng phiên bản trước.')
    protected=[frame_path,modeling/'snapshot_forecasts.csv',modeling/'active_prediction_model.json',
               modeling/'paper_trading_ledger.csv',ROOT/'web/data/gold_dashboard_data.json']
    protected+=list(p for p in (modeling/'stationary_shadow').rglob('*') if p.is_file())
    inputs=[reference_folder/'predictions.csv',reference_folder/'manifest.json']
    sources=[Path(__file__),ROOT/'scripts/analysis/quantile_challengers.py']
    hashes={str(p.relative_to(ROOT)).replace('\\','/'):file_hash(p) for p in protected+inputs+sources}
    manifest=dict(status='research_only',started_at=datetime.now(timezone.utc).isoformat(),parameters=PARAMETERS,
                  quantiles=[.1,.5,.9],point='q50_after_monotone_rearrangement',signal_margin=.01,
                  active_algorithm_fingerprint=source_id,sha256=hashes,
                  versions={name:importlib.metadata.version(name) for name in ('lightgbm','catboost','numpy','pandas','scikit-learn','scipy')})
    prepare_output(output,manifest)
    f=pd.read_csv(frame_path,low_memory=False).sort_values('date').reset_index(drop=True)
    f['date']=pd.to_datetime(f.date)
    audit=audit_targets(f,(3,));write_json(output/'target_audit.json',audit)
    if any(a['return_mismatches'] or a['exit_mismatches'] or a['invalid_price_rows'] for a in audit):
        raise ValueError('Frame không qua kiểm tra nhãn/giá.')
    reference=pd.read_csv(reference_folder/'predictions.csv',parse_dates=['date','exit_date','fold_start','train_last_exit_date','calibration_last_exit_date'])
    reference=reference.loc[reference.candidate.isin(['rf_small','zero'])].copy()
    reference=reference_intervals(reference)
    new=run_challengers(f)
    all_predictions=pd.concat([reference,new],ignore_index=True)
    all_predictions.to_csv(output/'predictions.csv',index=False,encoding='utf-8')
    evaluation=all_predictions.loc[all_predictions.date.ge('2023-01-01')]
    expected=reference.loc[reference.date.ge('2023-01-01')&reference.candidate.eq('rf_small')]
    for name,group in evaluation.groupby('candidate'):
        paired=expected[['date','actual']].merge(group[['date','actual']],on='date',suffixes=('_rf','_test'),validate='one_to_one')
        if (len(paired)!=len(expected) or len(group)!=len(expected)
                or not np.allclose(paired.actual_rf,paired.actual_test,atol=1e-10,rtol=0,equal_nan=True)):
            raise ValueError(f'{name} không cùng ngày/nhãn với RF.')
    candidates={name:evaluate_candidate(group,f) for name,group in evaluation.groupby('candidate')}
    intervals={name:interval_metrics(group) for name,group in evaluation.groupby('candidate')}
    residual={}
    for name,group in evaluation.groupby('candidate'):
        valid=group.loc[np.isfinite(group.actual)&np.isfinite(group.q10_residual)]
        err=valid.actual-valid.q10_residual
        residual[name]={'rows':len(valid),'breach_rate':float((err<0).mean()),
                        'pinball':float(np.maximum(.1*err,-.9*err).mean())}
    report=dict(status='research_only',independent_validation=False,snapshot_date=str(f.date.max().date()),
                candidates=candidates,intervals=intervals,residual_q10_comparison=residual,active_model_unchanged=True)
    for p in protected+inputs+sources:
        if file_hash(p)!=hashes[str(p.relative_to(ROOT)).replace('\\','/')]:
            raise ValueError('Artifact/mã/reference đổi trong lúc chạy: không công nhận kết quả.')
    if source_id!=algorithm_fingerprint():
        raise ValueError('Thuật toán tham chiếu thay đổi trong lúc chạy.')
    write_json(output/'report.json',report)
    (output/'report.md').write_text(markdown(report),encoding='utf-8')
    manifest.update(completed_at=datetime.now(timezone.utc).isoformat(),protected_artifacts_unchanged=True)
    write_json(output/'manifest.json',manifest)
    print(f'Hoàn tất đối chứng: {output}',flush=True)


if __name__=='__main__':
    main()
