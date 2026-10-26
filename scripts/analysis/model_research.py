"""Đối chứng hữu hạn theo tháng, tách nghiên cứu khỏi mô hình đang vận hành."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable
import numpy as np
import pandas as pd

from .model_diagnostics import _errors


@dataclass(frozen=True)
class Candidate:
    """Một cấu hình khóa trước chạy; window_years=None dùng toàn bộ train hợp lệ."""
    name: str
    kind: str
    top_k: int = 20
    window_years: int | None = None
    drop_group: str | None = None


def candidates() -> list[Candidate]:
    """Giới hạn 11 ứng viên, không dò cấu hình mới sau khi xem điểm ngoài mẫu."""
    return [Candidate('zero', 'zero'), Candidate('median_all', 'median'),
            Candidate('median_3y', 'median', window_years=3),
            Candidate('ridge20_all', 'ridge'), Candidate('ridge20_3y', 'ridge', window_years=3),
            *[Candidate(f'ridge20_without_{group}', 'ridge', drop_group=group)
              for group in ('domestic', 'global', 'calendar')],
            Candidate('rf20_all', 'rf'), Candidate('rf20_3y', 'rf', window_years=3),
            Candidate('rf120_reference', 'reference', top_k=120)]


def feature_group(name: str) -> str:
    """Gom cả cột gốc và biến trễ để phép bỏ nhóm không giữ lại bản sao cùng nguồn."""
    if name.startswith(('event_', 'severity_', 'channel_', 'days_until_')):
        return 'calendar'
    if name.startswith(('raw_news', 'news_')):
        return 'news'
    if name.startswith(('buy_price', 'sell_price', 'mid_price', 'spread_', 'sell_return',
                        'premium', 'source_count', 'source_dispersion')):
        return 'domestic'
    if name.startswith(('global_', 'gold_futures', 'lbma_', 'dxy_', 'oil_', 'silver_',
                        'sp500', 'treasury_', 'usd_', 'vix', 'GPR', 'fx_', 'gold_staleness', 'is_proxy')):
        return 'global'
    return 'macro_other'


def _validate(frame: pd.DataFrame, features: list[str], specs: list[Candidate]) -> None:
    """Từ chối mục tiêu/tương lai trong X trước cả khi ứng viên là baseline."""
    if 'date' not in frame or pd.to_datetime(frame.date, errors='coerce').isna().any() or frame.date.duplicated().any():
        raise ValueError('Ngày dữ liệu trùng hoặc không hợp lệ.')
    forbidden = ('future_', 'target_', 'exit_', 'net_return_', 'gross_sell_return_',
                 'positive_return_', 'gold_excess_return_', 'predicted_', 'prob_return_')
    if not features or len(set(features)) != len(features) or any(
        name not in frame or 'date' in name.lower() or name.startswith(forbidden) for name in features
    ):
        raise ValueError('Danh sách đặc trưng thiếu, trùng hoặc chứa nhãn/tương lai.')
    if not specs or len({s.name for s in specs}) != len(specs):
        raise ValueError('Ứng viên rỗng hoặc trùng tên.')
    if any(s.kind not in ('zero', 'median', 'ridge', 'rf', 'reference') or s.top_k < 1 or
           (s.window_years is not None and s.window_years < 1) for s in specs):
        raise ValueError('Cấu hình ứng viên không hợp lệ.')


def _rank_features(x: pd.DataFrame, y: pd.Series) -> list[str]:
    """Chỉ tính tương quan trên train; tối thiểu 200 quan sát và có biến thiên."""
    usable = x.columns[(x.count() >= 200) & (x.nunique() >= 2)]
    correlations = x[usable].corrwith(y).abs().dropna()
    # Tên cột giải hòa để kết quả không tùy thứ tự ngẫu nhiên khi tương quan bằng nhau.
    return sorted(correlations.index, key=lambda name: (-correlations[name], name))


def _model(kind: str):
    """Dùng Ridge cố định và RF nhỏ; reference giữ nguyên RF 350 cây hiện tại."""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if kind == 'reference':
        from .snapshot_calibration import make_point_model
        return make_point_model()
    if kind == 'ridge':
        return make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), Ridge(alpha=10., solver='lsqr'))
    return make_pipeline(SimpleImputer(strategy='median'), RandomForestRegressor(
        n_estimators=100, max_depth=4, min_samples_leaf=30, random_state=42, n_jobs=-1))


def run_monthly(
    frame: pd.DataFrame, features: list[str], horizon: int, specs: list[Candidate],
    *, start: str = '2021-01-01', progress: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """Huấn luyện đầu tháng, dự báo mọi ngày đã đáo hạn trong tháng đó.

    Tất cả ứng viên dùng chung tập test; thiếu đặc trưng thì báo lỗi thay vì
    âm thầm bỏ tháng khó. Nhãn train phải thoát trước đầu tháng, nghiêm hơn
    việc chỉ xét ngày vào lệnh. Không ghi đè bất kỳ artifact sản xuất nào.
    """
    f = frame.copy()
    f['date'] = pd.to_datetime(f.date)
    f = f.sort_values('date').reset_index(drop=True)
    _validate(f, features, specs)
    target, exit_col = f'net_return_{horizon}m', f'exit_date_{horizon}m'
    y = pd.to_numeric(f[target], errors='coerce')
    exits = pd.to_datetime(f[exit_col], errors='coerce')
    x = f[features].apply(pd.to_numeric, errors='coerce').replace([np.inf, -np.inf], np.nan)
    records = []
    for begin in pd.date_range(pd.Timestamp(start).to_period('M').start_time, f.date.max(), freq='MS'):
        end = begin + pd.DateOffset(months=1)
        test = f.date.ge(begin) & f.date.lt(end) & exits.le(f.date.max()) & np.isfinite(y)
        if not test.any():
            continue
        train_base = f.date.lt(begin) & exits.lt(begin) & np.isfinite(y)
        if train_base.sum() < 300:
            continue
        if progress:
            progress(f'{horizon}m {begin:%Y-%m}: {int(test.sum())} ngày đánh giá')
        # Cache xếp hạng dùng chung trong tháng; bỏ nhóm trước top_k để phép ablation đúng nghĩa.
        rankings = {}
        for spec in specs:
            train = train_base.copy()
            if spec.window_years is not None:
                train &= f.date.ge(begin - pd.DateOffset(years=spec.window_years))
            if train.sum() < 300:
                raise ValueError(f'Thiếu train cho {spec.name} ở {begin:%Y-%m}.')
            selected = []
            if spec.kind == 'zero':
                predicted = np.zeros(int(test.sum()))
            elif spec.kind == 'median':
                predicted = np.full(int(test.sum()), float(y[train].median()))
            else:
                key = spec.window_years
                if key not in rankings:
                    rankings[key] = _rank_features(x.loc[train], y.loc[train])
                selected = [name for name in rankings[key] if feature_group(name) != spec.drop_group][:spec.top_k]
                if not selected:
                    raise ValueError(f'Không đủ đặc trưng cho {spec.name} ở {begin:%Y-%m}.')
                model = _model(spec.kind)
                model.fit(x.loc[train, selected], y.loc[train])
                predicted = model.predict(x.loc[test, selected])
            if not np.isfinite(predicted).all():
                raise ValueError(f'Dự báo vô hạn ở {spec.name}.')
            for index, prediction in zip(f.index[test], predicted):
                records.append({'date': f.at[index, 'date'], 'exit_date': exits.at[index],
                                'horizon_months': horizon, 'fold_start': begin, 'candidate': spec.name,
                                'train_last_exit_date': exits[train].max(), 'train_rows': int(train.sum()),
                                'selected_features': '|'.join(selected), 'actual': float(y.at[index]),
                                'predicted': float(prediction)})
    return pd.DataFrame(records)


def select_annual(predictions: pd.DataFrame, *, evaluation_start: int = 2023) -> list[dict]:
    """Chọn theo MAE bình quân tháng trong 24 tháng trước, chỉ dùng nhãn đã biết.

    Đây là lựa chọn lồng theo thời gian: ứng viên được huấn luyện hàng tháng
    bên trong, cấu hình được khóa cho cả năm đánh giá bên ngoài. Các ứng
    viên cùng phải có đủ ngày; thiếu bằng chứng thì giữ baseline zero.
    """
    p = predictions.copy()
    if p.empty:
        return []
    for field in ('date', 'exit_date'):
        p[field] = pd.to_datetime(p[field])
    if p.duplicated(['horizon_months', 'candidate', 'date']).any():
        raise ValueError('Dự báo ứng viên trùng ngày.')
    choices = []
    for h, rows in p.groupby('horizon_months'):
        names = sorted(rows.candidate.unique())
        if 'zero' not in names:
            raise ValueError('Cần baseline zero để lựa chọn an toàn.')
        for year in range(evaluation_start, rows.date.max().year + 1):
            cutoff = pd.Timestamp(year, 1, 1)
            past = rows.loc[rows.date.ge(cutoff - pd.DateOffset(years=2)) & rows.date.lt(cutoff) & rows.exit_date.lt(cutoff)].copy()
            counts = past.groupby('date').candidate.nunique()
            past = past.loc[past.date.isin(counts[counts.eq(len(names))].index)]
            past['month'] = past.date.dt.strftime('%Y-%m')
            scores = {}
            if past.date.nunique() >= 120 and past.month.nunique() >= 6:
                past['ae'] = abs(past.predicted - past.actual)
                scores = past.groupby(['candidate', 'month']).ae.mean().groupby('candidate').mean().to_dict()
            winner = min(scores, key=lambda name: (scores[name], name != 'zero', name)) if scores else 'zero'
            choices.append({'horizon_months': int(h), 'year': year, 'candidate': winner,
                            'selection_rows_per_candidate': int(past.date.nunique()),
                            'selection_months': int(past.month.nunique()),
                            'selection_last_exit_date': str(past.exit_date.max().date()) if not past.empty else None,
                            'scores_monthly_mae': scores, 'fallback': not bool(scores)})
    return choices


def _score(rows: pd.DataFrame) -> dict:
    """Báo cáo cả điểm theo ngày, bình quân tháng và số kỳ nắm giữ không chồng lấn."""
    out = _errors(rows)
    monthly = rows.assign(month=pd.to_datetime(rows.date).dt.strftime('%Y-%m'), ae=abs(rows.predicted - rows.actual))
    out['monthly_macro_mae'] = float(monthly.groupby('month').ae.mean().mean())
    last_exit, count = pd.Timestamp.min, 0
    for row in rows.sort_values('date').itertuples():
        if row.date >= last_exit:
            count += 1
            last_exit = row.exit_date
    out['nonoverlapping_windows'] = count
    out['mae_improvement_vs_zero'] = 1 - out['mae'] / out['zero_mae'] if out['zero_mae'] > 0 else None
    return out


def summarize_research(predictions: pd.DataFrame, selections: list[dict], *, evaluation_start: int = 2023) -> dict:
    """Phân biệt bảng xếp hạng đã xem toàn lịch sử và chuỗi chọn cấu hình trước năm."""
    p = predictions.loc[pd.to_datetime(predictions.date).dt.year.ge(evaluation_start)].copy()
    summaries, yearly, nested, ablations = [], [], [], []
    for h, rows in p.groupby('horizon_months'):
        expected = set(rows.date)
        if any(set(group.date) != expected for _, group in rows.groupby('candidate')):
            raise ValueError('Các ứng viên không có cùng tập ngày đánh giá.')
        for name, group in rows.groupby('candidate'):
            summaries.append({'horizon_months': int(h), 'candidate': name, **_score(group)})
            for year, annual in group.groupby(pd.to_datetime(group.date).dt.year):
                yearly.append({'horizon_months': int(h), 'candidate': name, 'year': int(year), **_score(annual)})
        selected = []
        for choice in selections:
            if choice['horizon_months'] == h:
                selected.append(rows.loc[rows.candidate.eq(choice['candidate']) & pd.to_datetime(rows.date).dt.year.eq(choice['year'])])
        chosen = pd.concat(selected, ignore_index=True) if selected else pd.DataFrame()
        if not chosen.empty:
            nested.append({'horizon_months': int(h), **_score(chosen)})
        base = next((s for s in summaries if s['horizon_months'] == h and s['candidate'] == 'ridge20_all'), None)
        if base:
            for item in summaries:
                if item['horizon_months'] == h and item['candidate'].startswith('ridge20_without_'):
                    ablations.append({'horizon_months': int(h), 'candidate': item['candidate'],
                                      'mae_change_vs_full': item['mae'] - base['mae'],
                                      'interpretation': 'negative_means_removal_helped_not_causal_proof'})
    return {'status': 'research_only', 'independent_validation': False,
            'notice': 'Lịch sử đã dùng phát triển; kết quả không cấp validated hoặc thay tín hiệu giao dịch.',
            'candidate_ranking_is_retrospective': True, 'candidates': summaries, 'by_year': yearly,
            'nested_selection': nested, 'ablations': ablations,
            'registry': [asdict(s) for s in candidates()]}
