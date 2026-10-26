#!/usr/bin/env python3
"""
Prepares optimized JSON dataset for the Gold Market Visualizer Dashboard.
Reads from data/lake/ and outputs to web/data/gold_dashboard_data.json.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts._bootstrap import bootstrap
bootstrap()
from gold_collectors.units import OZ_PER_LUONG


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _build_validated_recommendations(lake: Path, *, expected_snapshot_date: str | None = None) -> dict:
    """Chỉ cho phép mua khi snapshot đồng bộ dữ liệu và đã qua kiểm định.

    `ok` chỉ nói script chạy xong, không chứng minh mô hình đáng tin cậy.
    Thiếu ngày dữ liệu đối chiếu, kỳ hạn hoặc metadata mới đều giữ quan sát.
    """
    snapshot_path = lake / "modeling" / "snapshot_forecasts.csv"
    if not snapshot_path.exists():
        return {}

    rows = load_csv(snapshot_path)
    if not rows:
        return {}

    snapshot_date = rows[0].get("snapshot_date", "")
    horizons_data = []
    dataset_reasons = []
    # Nhãn validated trong CSV phải có báo cáo cùng ngày, cùng giao thức
    # và đủ tất cả tiêu chí. Không tự tin một nhãn có thể được sửa bằng tay.
    report_path = lake / "modeling" / "snapshot_validation_report.json"
    report, validation_details = {}, {}
    try:
        candidate = json.loads(report_path.read_text(encoding="utf-8"))
        details = candidate.get("horizons", []) if isinstance(candidate, dict) else []
        if (isinstance(details, list) and len(details) == 3
                and all(isinstance(item, dict) and type(item.get("horizon_months")) is int for item in details)
                and sorted(item["horizon_months"] for item in details) == [1, 3, 5]):
            report = candidate
            validation_details = {item["horizon_months"]: item for item in details}
    except (OSError, ValueError, TypeError):
        # Báo cáo thiếu/hỏng không được làm cổng mua mở lại hoặc làm dashboard lỗi.
        pass
    required_checks = (
        "inputs_verified", "enough_rows", "enough_time_span", "enough_nonoverlap",
        "mae_vs_zero", "brier_vs_baseline", "q10_coverage", "q10_pinball_vs_baseline", "probability_calibration",
    )
    history_report, history_details = {}, {}
    try:
        candidate = json.loads((lake / 'modeling' / 'snapshot_historical_report.json').read_text(encoding='utf-8'))
        details = candidate.get('horizons', []) if isinstance(candidate, dict) else []
        if (isinstance(details, list) and len(details) == 3
                and all(isinstance(item, dict) and type(item.get('horizon_months')) is int for item in details)
                and sorted(item['horizon_months'] for item in details) == [1, 3, 5]
                and candidate.get('evaluation_kind') == 'historical_screening'
                and candidate.get('independent_validation') is False):
            history_report = candidate
            history_details = {item['horizon_months']: item for item in details}
    except (OSError, ValueError, TypeError):
        pass
    try:
        datetime.strptime(expected_snapshot_date or "", "%Y-%m-%d")
    except ValueError:
        dataset_reasons.append("Không có ngày dữ liệu hợp lệ để đối chiếu snapshot.")
    if not expected_snapshot_date or any(r.get("snapshot_date") != expected_snapshot_date for r in rows):
        dataset_reasons.append("Ngày snapshot không khớp ngày dữ liệu dashboard.")
    if sorted(str(r.get("horizon_months") or "") for r in rows) != ["1", "3", "5"]:
        dataset_reasons.append("Snapshot phải có đủ và duy nhất ba kỳ hạn 1, 3, 5 tháng.")

    def finite_number(value: str | None) -> float | None:
        """Đổi số lỗi, NaN và vô cực thành null để JSON luôn đọc được trên trình duyệt."""
        try:
            number = float(value)
            return number if math.isfinite(number) else None
        except (ValueError, TypeError):
            return None

    for r in rows:
        try:
            h_months = int(r.get("horizon_months", 0))
            h_label = r.get("horizon_label", f"{h_months} tháng")
            target_date = r.get("target_date", "")
            pred_ret = finite_number(r.get("predicted_net_return"))
            q10_ret = finite_number(r.get("q10_predicted_net_return"))
            prob_pos = finite_number(r.get("prob_return_positive"))
            buy_sig = str(r.get("buy_signal") or "").strip().lower() in ("true", "1")
        except (ValueError, TypeError):
            continue

        reasons = list(dataset_reasons)
        if r.get("status") != "validated":
            reasons.append("Mô hình chưa vượt qua kiểm định chất lượng độc lập.")
        evidence = validation_details.get(h_months, {})
        checks = evidence.get("checks", {})
        report_matches = (bool(r.get("validation_protocol_id"))
                          and r.get("validation_protocol_id") == report.get("protocol_id")
                          and report.get("snapshot_date") == expected_snapshot_date == r.get("snapshot_date"))
        if (not report_matches or evidence.get("status") != "validated" or not isinstance(checks, dict)
                or not all(checks.get(name) is True for name in required_checks)):
            reasons.append("Chưa có báo cáo kiểm định đạt đầy đủ tiêu chí, cùng ngày và cùng giao thức.")
            if report_matches and isinstance(evidence.get("reasons"), list):
                reasons.extend(message for message in evidence["reasons"] if isinstance(message, str))
        calibration_rows = finite_number(r.get("calibration_rows"))
        calibrated = (r.get("probability_method") == "temporal_oos_empirical_laplace"
                      and calibration_rows is not None and calibration_rows >= 60)
        if not calibrated:
            reasons.append("Chưa đủ sai số dự báo ngoài mẫu để ước lượng xác suất lãi.")
            # Không tiếp tục hiển thị xác suất cũ suy ra từ sai số trong mẫu.
            prob_pos = None
        if pred_ret is None or q10_ret is None or prob_pos is None or not 0 <= prob_pos <= 1:
            reasons.append("Số liệu dự báo hoặc xác suất không hợp lệ.")
            if prob_pos is not None and not 0 <= prob_pos <= 1:
                prob_pos = None
        # Bật tín hiệu phải đồng thời qua cổng kiểm định và đúng ngưỡng nghiệp vụ;
        # không tin cờ buy_signal cũ nếu xác suất hoặc Q10 đã không còn thỏa điều kiện.
        buy_sig = bool(not reasons and buy_sig and prob_pos >= 0.50 and q10_ret >= -0.10)
        action = "Quan sát — chưa đủ điều kiện" if reasons else ("Mua tích lũy" if buy_sig else "Không mua mới")
        badge_type = "warning" if reasons else ("positive" if buy_sig else "negative")

        pred_pct = round(pred_ret * 100, 2) if pred_ret is not None else None
        q10_pct = round(q10_ret * 100, 2) if q10_ret is not None else None
        prob_pct = round(prob_pos * 100, 1) if prob_pos is not None else None

        # Kỳ hạn dùng tháng lịch; ngày thoát thực tế là phiên SJC đầu tiên từ target_date.
        horizon_desc = h_label
        # Chỉ diễn giải số liệu có trong snapshot; không dùng giá hoặc premium viết cứng từ lần chạy cũ.
        if pred_pct is not None and q10_pct is not None and prob_pct is not None:
            rationale = (
                f"Lợi suất ròng dự báo {pred_pct:+.2f}%; Q10 {q10_pct:+.2f}%; "
                f"xác suất lợi suất dương ước lượng {prob_pct:.1f}%. "
                f"Ngày tròn {h_months} tháng: {target_date}; khi đánh giá dùng phiên SJC hợp lệ đầu tiên từ ngày này."
            )
        else:
            rationale = "Chưa đủ số liệu hợp lệ để trình bày đầy đủ dự báo và xác suất lãi."
        if reasons:
            rationale += " " + " ".join(reasons)

        # Hai mức bằng chứng tách riêng: điểm lịch sử không mở cổng mua thực tế,
        # và số mẫu lịch sử không được cộng vào tiến độ kiểm chứng tiến cứu.
        historical = history_details.get(h_months, {})
        history_matches = (history_report.get('snapshot_date') == expected_snapshot_date == r.get('snapshot_date')
                           and bool(r.get('validation_protocol_id'))
                           and history_report.get('protocol_id') == r.get('validation_protocol_id'))
        history_status = historical.get('status') if history_matches else 'historical_insufficient'
        if history_status not in ('historical_passed', 'historical_failed', 'historical_insufficient'):
            history_status = 'historical_insufficient'
        history_checks = historical.get('checks', {})
        if history_status == 'historical_passed' and (not isinstance(history_checks, dict)
                                                     or not all(history_checks.get(name) is True for name in required_checks)):
            history_status = 'historical_insufficient'
        history_metrics = historical.get('metrics', {}) if history_matches else {}
        if not isinstance(history_metrics, dict):
            history_metrics = {}
        prospective_status = r.get('status') if report_matches and evidence.get('status') == r.get('status') else 'unvalidated'
        if prospective_status == 'validated' and (not isinstance(checks, dict)
                                                 or not all(checks.get(name) is True for name in required_checks)):
            prospective_status = 'validation_failed'
        prospective_metrics = evidence.get('metrics', {}) if report_matches else {}
        if not isinstance(prospective_metrics, dict):
            prospective_metrics = {}
        policy = report.get('policy', {}) if report_matches and isinstance(report.get('policy'), dict) else {}
        simulation_buy = bool(history_status == 'historical_passed' and not dataset_reasons and calibrated
                              and pred_ret is not None and q10_ret is not None and prob_pos is not None
                              and 0.5 <= prob_pos <= 1 and q10_ret >= -0.1)

        horizons_data.append({
            "horizon_months": h_months,
            "horizon_label": horizon_desc,
            "target_date": target_date,
            "predicted_net_return": pred_pct,
            "q10_predicted_net_return": q10_pct,
            "prob_return_positive": prob_pct,
            "buy_signal": buy_sig,
            "action": action,
            "badge_type": badge_type,
            "rationale": rationale,
            "status": r.get("status", "unvalidated"),
            "validation_protocol_id": r.get("validation_protocol_id", ""),
            "blocked_reasons": reasons,
            "simulation_buy_signal": simulation_buy,
            "historical": {
                "status": history_status,
                "label": {'historical_passed': 'Đạt đánh giá lịch sử', 'historical_failed': 'Chưa đạt đánh giá lịch sử',
                          'historical_insufficient': 'Chưa đủ dữ liệu lịch sử'}[history_status],
                "metrics": {key: finite_number(history_metrics.get(key)) for key in ('matured_rows', 'mae', 'zero_baseline_mae', 'brier', 'q10_breach_rate')},
                "notice": 'Sàng lọc nghiên cứu trên lịch sử đã xem; không thay thế kiểm chứng thực tế.',
            },
            "prospective": {
                "status": prospective_status,
                "label": {'validated': 'Đạt kiểm chứng thực tế', 'validation_failed': 'Chưa đạt kiểm chứng thực tế',
                          'validation_pending': 'Đang tích lũy bằng chứng thực tế'}.get(prospective_status, 'Chưa đủ bằng chứng thực tế'),
                "metrics": {key: finite_number(prospective_metrics.get(key)) for key in ('matured_rows', 'nonoverlapping_windows', 'origin_span_days')},
                "targets": {key: finite_number(policy.get(key)) for key in ('min_matured_rows', 'min_nonoverlapping_windows', 'min_origin_span_days')},
                "validation_start": report.get('validation_start', '') if report_matches else '',
            },
        })

    horizons_data.sort(key=lambda x: x["horizon_months"])

    buy_horizons = [h for h in horizons_data if h["buy_signal"]]
    if buy_horizons:
        # Bất kỳ kỳ hạn nào bật tín hiệu đều phải được nêu rõ; đặc biệt không bỏ sót ba tháng.
        labels = {1: "1 THÁNG", 3: "3 THÁNG", 5: "5 THÁNG"}
        buy_names = ", ".join(labels.get(h["horizon_months"], h["horizon_label"]) for h in buy_horizons)
        primary_action = f"CÓ TÍN HIỆU MUA: {buy_names}"
        action_theme = "positive"
        executive_summary = (
            f"Snapshot {snapshot_date}: mô hình bật tín hiệu mua ở kỳ hạn {buy_names.lower()}. "
            "Các kỳ hạn còn lại chưa đạt đồng thời ngưỡng xác suất lãi và Q10; "
            "cần đối chiếu dữ liệu và kiểm định ngoài mẫu trước khi sử dụng để giao dịch."
        )
    else:
        primary_action = "KHÔNG MUA MỚI / QUAN SÁT THỊ TRƯỜNG"
        action_theme = "negative"
        executive_summary = (
            f"Snapshot {snapshot_date}: mô hình không bật tín hiệu mua ở các kỳ hạn đã tính. "
            "Xem lợi suất ròng, Q10 và xác suất lãi ước lượng của từng kỳ hạn ở bên dưới."
        )
        if any(h["blocked_reasons"] for h in horizons_data):
            action_theme = "warning"
            executive_summary = (
                f"Snapshot {snapshot_date}: giữ trạng thái quan sát vì chưa đủ điều kiện kiểm định, "
                "hiệu chỉnh xác suất hoặc đồng bộ ngày dữ liệu. Các dự báo chỉ dùng để theo dõi nghiên cứu."
            )

    return {
        "snapshot_date": snapshot_date,
        "primary_signal": "buy" if buy_horizons else "observe",
        "primary_action": primary_action,
        "action_theme": action_theme,
        "executive_summary": executive_summary,
        "horizons": horizons_data,
        "rules_explained": [
            "Lợi suất ròng được tính từ giá bán khi mua đến giá mua khi thoát vị thế, nên đã tính chênh lệch mua - bán.",
            "Bộ lọc tín hiệu: P(lãi) ≥ 50% và Q10 ≥ -10%; Q10 là phân vị 10% ước lượng, không phải mức lỗ tối đa.",
            "Dự báo điểm dùng Random Forest; Q10 dùng Gradient Boosting Quantile trên dữ liệu hiện có.",
            "Kỳ hạn là tháng lịch; ngày thoát là phiên SJC đầu tiên vào hoặc sau ngày tròn tháng.",
            "Chỉ bật tín hiệu khi mô hình đã kiểm định và snapshot khớp ngày dữ liệu; thiếu bằng chứng thì giữ quan sát.",
            "Xác suất lãi ước lượng từ sai số dự báo ngoài mẫu theo thời gian; không dùng sai số huấn luyện và không phải cam kết lợi nhuận.",
            "Đánh giá lịch sử phục vụ nghiên cứu; chỉ kiểm chứng thực tế đạt mới cho phép bật tín hiệu mua. Tín hiệu mô phỏng không tạo vị thế giao dịch.",
        ]
    }


def _snapshot_quote(lake: Path, snapshot_date: str) -> tuple[float | None, float | None]:
    """Lấy giá đúng ngày từ frame đã dùng dự báo; không dùng giá mới ghép dự báo cũ.

    Đọc tuần tự thay vì nạp toàn bộ bảng hàng trăm cột vào RAM. Frame vắng
    thì dùng bảng SJC gốc cùng ngày; frame có nhưng thiếu ngày thì trả thiếu,
    để không trộn hai phiên dữ liệu khác nhau một cách âm thầm.
    """
    frame = lake / 'modeling/model_frame_daily.csv'
    source = frame if frame.exists() else lake / 'gold_quotes_sjc_historical.csv'
    if not source.exists():
        return None, None
    buy_col, sell_col = ('buy_price', 'sell_price') if source == frame else ('buy', 'sell')
    quote, last_time = (None, None), ''
    with source.open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            if row.get('date', '')[:10] != snapshot_date:
                continue
            try:
                buy, sell = float(row[buy_col]), float(row[sell_col])
            except (KeyError, TypeError, ValueError):
                continue
            stamp = row.get('timestamp') or ''
            if math.isfinite(buy) and math.isfinite(sell) and 0 < buy <= sell and stamp >= last_time:
                quote, last_time = (buy, sell), stamp
    return quote


def build_recommendations(lake: Path, *, expected_snapshot_date: str | None = None,
                          signal_mode: str = 'direct') -> dict:
    """Đưa tín hiệu dự báo trực tiếp lên UI; kiểm định vẫn là metadata riêng.

    Người dùng đã chọn bỏ cổng kiểm định đối với tín hiệu hiển thị. Chế độ
    validated giữ hành vi cũ để đối chiếu; không sửa status hoặc sổ giao dịch
    và không tự biến tín hiệu dự báo thành bằng chứng validated.
    """
    if signal_mode not in ('direct', 'validated'):
        raise ValueError('Chế độ tín hiệu không hợp lệ.')
    rec = _build_validated_recommendations(lake, expected_snapshot_date=expected_snapshot_date)
    if not rec or signal_mode == 'validated':
        return rec
    from scripts.analysis.forecast_signals import direct_signal, NEUTRAL_MARGIN, PRIMARY_HORIZON_MONTHS
    rows = load_csv(lake / 'modeling/snapshot_forecasts.csv')
    buy, sell = _snapshot_quote(lake, rec['snapshot_date'])
    dataset_valid = (bool(expected_snapshot_date)
                     and all(r.get('snapshot_date') == expected_snapshot_date for r in rows)
                     and sorted(str(r.get('horizon_months') or '') for r in rows) == ['1', '3', '5'])
    try:
        datetime.strptime(expected_snapshot_date or '', '%Y-%m-%d')
    except ValueError:
        dataset_valid = False
    originals = {int(r['horizon_months']): r for r in rows if str(r.get('horizon_months', '')).isdigit()}
    activated = {}
    # Mỗi kỳ hạn có bản khóa và hiệu chỉnh riêng. Cấu hình lỗi thì tất cả
    # kỳ hạn Quan sát; lỗi một dự báo chỉ chặn kỳ hạn tương ứng.
    if (lake/'modeling/active_prediction_model.json').exists():
        try:
            from scripts.analysis.stationary_activation import load_active_forecast
            config = json.loads((lake/'modeling/active_prediction_model.json').read_text(encoding='utf-8'))
            if not isinstance(config, dict):
                raise ValueError('Cấu hình phải là một đối tượng JSON.')
            horizons = [int(key) for key in config['horizons']] if 'horizons' in config else [int(config['horizon_months'])]
            if not horizons or any(h not in (1,3,5) for h in horizons):
                raise ValueError('Danh sách kỳ hạn kích hoạt không hợp lệ.')
        except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
            horizons = (1,3,5)
            activated = {h: (None, f'Cấu hình mô hình cải tiến không hợp lệ: {exc}') for h in horizons}
        for horizon in horizons:
            if horizon in activated:
                continue
            try:
                activated[horizon] = (load_active_forecast(lake/'modeling', expected_snapshot_date or '', horizon=horizon), None)
            except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
                activated[horizon] = (None, f'Chưa có dự báo hợp lệ từ mô hình cải tiến: {exc}')
    for h in rec['horizons']:
        active, activation_error = activated.get(h['horizon_months'], (None, None))
        row = originals.get(h['horizon_months'], {})
        reasons = []
        if active is not None or activation_error is not None:
            row = {**row, **(active or {}), 'predicted_net_return': active.get('predicted_net_return') if active else None}
            validation = active.get('validation', {}) if active else {}
            state = validation.get('status', 'unvalidated')
            checks = validation.get('checks', {})
            from scripts.analysis.snapshot_validation import REQUIRED_CHECKS
            verified = state == 'validated' and isinstance(checks, dict) and all(checks.get(name) is True for name in REQUIRED_CHECKS)
            if state == 'validated' and not verified:
                state = 'validation_failed'
            def percent(key):
                value = active.get(key) if active else None
                return round(float(value)*100, 2) if value is not None else None
            quality = active.get('calibration_quality', {}) if active else {}
            selection = active.get('forecast_selection', {}) if active else {}
            research_forecast = selection.get('forecast_role') == 'research'
            calibration_note = ''
            if quality and (not quality.get('probability_qualified') or not quality.get('q10_qualified')):
                calibration_note = 'Chỉ số chưa đạt kiểm tra lịch sử được để trống. ' + ' '.join(quality.get('reasons', []))
            h.update(point_model=f"stationary_{active['candidate'] if active else 'unavailable'}_{h['horizon_months']}m",
                     model_label=('Mốc tham chiếu lợi suất 0' if active and active.get('candidate') == 'zero' else
                                  'Mô hình dự báo thử nghiệm' if research_forecast else 'Mô hình cải tiến'),
                     forecast_note=selection.get('reason',''),
                     forecast_selection=selection,
                     calibration_note=calibration_note,
                     calibration_quality=quality,
                     probability_method=active.get('probability_method') if active else None,
                     calibration_rows=active.get('calibration_rows',0) if active else 0,
                     q10_model='adaptive_temporal_oos_q10_v2' if quality else 'temporal_oos_residual_q10',
                     predicted_net_return=percent('predicted_net_return'),
                     q10_predicted_net_return=percent('q10_predicted_net_return'),
                     prob_return_positive=percent('prob_return_positive'),
                     # Số ước tính gốc dùng riêng cho giao diện theo yêu cầu người xem.
                     # Đổi từ tỷ lệ sang phần trăm; không cấp trạng thái validated
                     # hoặc dùng các số này để thay cờ giao dịch đã kiểm định.
                     research_q10_predicted_net_return=percent('research_q10_predicted_net_return'),
                     research_prob_return_positive=percent('research_prob_return_positive'),
                     status=state, buy_signal=False, simulation_buy_signal=False,
                     validation_protocol_id=validation.get('protocol_id',''),
                     blocked_reasons=[str(reason) for reason in validation.get('reasons',[])],
                     historical={'status':'historical_insufficient','label':'Xem báo cáo mô hình cải tiến', 'metrics':{}},
                     prospective={'status':state,'label':{'validation_pending':'Đang tích lũy bằng chứng thực tế',
                        'validation_failed':'Chưa đạt kiểm chứng thực tế','validated':'Đạt kiểm chứng thực tế'}.get(state,'Chưa đủ bằng chứng thực tế'),
                        'metrics':validation.get('metrics',{}),'targets':{
                            key:(active or {}).get('validation_policy',{}).get(key) for key in
                            ('min_matured_rows','min_nonoverlapping_windows','min_origin_span_days')},
                        'validation_start':validation.get('validation_start','')})
            # Giữ cờ kiểm định khác cờ hiển thị trực tiếp, kể cả sau khi đổi model.
            h['buy_signal'] = bool(verified and active and active.get('prob_return_positive') is not None
                                  and active['prob_return_positive'] >= .5 and active.get('q10_predicted_net_return') is not None
                                  and active['q10_predicted_net_return'] >= -.1)
            if activation_error:
                reasons.append(activation_error)
        if not dataset_valid:
            reasons.append('Ngày dự báo không khớp dữ liệu hoặc thiếu ba kỳ hạn 1, 3, 5 tháng.')
        if buy is None or sell is None:
            reasons.append('Chưa có giá mua/bán hợp lệ đúng ngày dự báo.')
        # Giá đầu vào phải có và khớp, kể cả khi frame có đủ giá: nếu thiếu
        # mẫu số gốc thì không chứng minh được phép đổi sang lợi suất giữ vàng.
        try:
            entry = float(row.get('entry_sell_price'))
            if sell is None or not math.isfinite(entry) or entry <= 0 or not math.isclose(entry, sell, rel_tol=1e-9):
                reasons.append('Giá bán đầu vào không khớp snapshot.')
        except (ValueError, TypeError):
            reasons.append('Giá bán đầu vào snapshot thiếu hoặc không hợp lệ.')
        band = active['margin'] if active is not None else NEUTRAL_MARGIN
        decision = direct_signal(row.get('predicted_net_return') if not reasons else None, buy, sell, margin=band)
        if not reasons and decision['predicted_hold_return'] is None:
            reasons.append(decision['reason'])
        h['validated_buy_signal'] = h['buy_signal']
        h['validation_reasons'] = h['blocked_reasons']
        h.update(signal=decision['signal'], action=decision['action'], badge_type=decision['badge_type'],
                 signal_margin_pct=band*100,
                 buy_signal=decision['signal'] == 'buy', sell_signal=decision['signal'] == 'sell',
                 predicted_hold_return=round(decision['predicted_hold_return'] * 100, 2) if decision['predicted_hold_return'] is not None else None,
                 rationale=' '.join(reasons) if reasons else decision['reason'], blocked_reasons=reasons)
    primary = next((h for h in rec['horizons'] if h['horizon_months'] == PRIMARY_HORIZON_MONTHS), None)
    rec.update(signal_mode='direct_forecast', neutral_margin_pct=primary.get('signal_margin_pct',NEUTRAL_MARGIN*100) if primary else NEUTRAL_MARGIN*100,
               primary_model_label=primary.get('model_label','Dự báo mô hình') if primary else 'Dự báo mô hình',
               primary_horizon_months=PRIMARY_HORIZON_MONTHS,
               primary_signal=primary['signal'] if primary else 'observe',
               primary_action=primary['action'].upper() if primary else 'QUAN SÁT',
               action_theme=primary['badge_type'] if primary else 'warning',
                executive_summary=f"Theo dự báo kỳ hạn {PRIMARY_HORIZON_MONTHS} tháng: {primary['rationale']}" if primary else 'Chưa có dự báo hợp lệ cho kỳ hạn chính.',
               rules_explained=[
                   f'Mua khi lợi suất mua mới dự báo lớn hơn {NEUTRAL_MARGIN*100:g}%, đã tính chênh lệch giá mua–bán.',
                   f'Bán áp dụng cho vàng đang giữ: giá mua lại dự báo thấp hơn giá mua lại hiện tại trên {NEUTRAL_MARGIN*100:g}%.',
                   'Còn lại Quan sát; đây là vùng trung tính nghiệp vụ, không phải ngưỡng tối ưu đã kiểm định.',
                   'Tín hiệu phản ánh trực tiếp dự báo; xác suất, Q10 và kết quả kiểm định nằm trong Chi tiết.',
                   f'Tín hiệu chính dùng kỳ hạn {PRIMARY_HORIZON_MONTHS} tháng; từng kỳ hạn có tín hiệu riêng.',
               ])
    return rec


def main():
    root = Path(__file__).resolve().parent.parent
    lake = root / "data" / "lake"
    out_dir = root / "web" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Dùng bảng vừa dựng cùng model frame; bản sao gold_prices cũ có thể
    # vẫn chứa phép quy đổi sai dù pipeline đã sửa dữ liệu chuẩn.
    enriched_file = lake / "pipeline_output_premium_enriched.csv"
    if not enriched_file.exists():
        enriched_file = lake / "gold_prices" / "gold_daily_enriched.csv"
        if not enriched_file.exists():
            enriched_file = lake / "gold_daily_enriched.csv"

    # Dashboard và model phải cùng đọc bảng event đã được làm mới; bảng
    # event_regime_panel.csv cũ không có các tin RSS mới thu thập.
    events_file = lake / "pipeline_output_event_regime.csv"

    print(f"Reading enriched gold data from {enriched_file}...")
    enriched_rows = load_csv(enriched_file)

    timeline = []
    ath_premium = 0.0
    ath_premium_date = ""
    latest_valid_premium = None

    for r in enriched_rows:
        d = r.get("date")
        if not d:
            continue

        def parse_f(val):
            try:
                return float(val) if val not in ("", None, "null") else None
            except ValueError:
                return None

        buy = parse_f(r.get("buy_consensus"))
        sell = parse_f(r.get("sell_consensus"))
        spread = parse_f(r.get("spread_abs"))
        global_usd = parse_f(r.get("global_gold_usd_oz"))
        global_vnd = parse_f(r.get("global_gold_vnd_per_luong"))
        premium = parse_f(r.get("premium"))
        premium_pct = parse_f(r.get("premium_pct"))
        usd_vnd = parse_f(r.get("usd_vnd"))

        # Tính lại từ USD/oz và tỷ giá để bản sao legacy không mang hệ số
        # khối lượng sai lên UI. Premium của biểu đồ giữ nghĩa giá SJC
        # trung bình mua/bán trừ tham chiếu, khác premium giá bán của model.
        valid_reference = all(value is not None and math.isfinite(value) and value > 0
                              for value in (global_usd, usd_vnd))
        global_vnd = global_usd * usd_vnd * OZ_PER_LUONG if valid_reference else None
        valid_quote = all(value is not None and math.isfinite(value) and value > 0 for value in (buy,sell))
        premium = (buy+sell)/2-global_vnd if valid_quote and global_vnd is not None else None
        premium_pct = premium/global_vnd if premium is not None else None

        if premium is not None and premium > ath_premium:
            ath_premium = premium
            ath_premium_date = d

        if premium is not None:
            latest_valid_premium = {
                "date": d,
                "premium": premium,
                "premium_pct": premium_pct,
                "global_vnd": global_vnd,
            }

        timeline.append({
            "d": d,
            "b": round(buy, 0) if buy is not None else None,
            "s": round(sell, 0) if sell is not None else None,
            "sp": round(spread, 0) if spread is not None else None,
            "gu": round(global_usd, 2) if global_usd is not None else None,
            "gv": round(global_vnd, 0) if global_vnd is not None else None,
            "p": round(premium, 0) if premium is not None else None,
            "pp": round(premium_pct * 100, 2) if premium_pct is not None else None,
            "fx": round(usd_vnd, 0) if usd_vnd is not None else None,
        })

    # Sort timeline chronologically
    timeline.sort(key=lambda x: x["d"])

    # Load high-signal events across 2011 - 2026
    events = []
    curated_milestones = [
        {"date": "2024-06-03", "type": "sbv_policy", "title": "NHNN chính thức triển khai bán vàng miếng trực tiếp qua 4 NHTM Nhà nước (Vietcombank, BIDV, VietinBank, Agribank) và SJC", "category": "policy"},
        {"date": "2024-05-23", "type": "policy_inspection", "title": "Thanh tra liên ngành việc chấp hành chính sách, pháp luật trong hoạt động kinh doanh vàng", "category": "policy"},
        {"date": "2024-04-23", "type": "policy_auction", "title": "NHNN tái khởi động các phiên đấu thầu vàng miếng SJC sau 11 năm tạm ngưng", "category": "policy"},
        {"date": "2024-02-19", "type": "than_tai", "title": "Ngày vía Thần Tài Giáp Thìn 2024 (Mùng 10 tháng Giêng): Nhu cầu vàng nhẫn và vàng miếng tăng vọt", "category": "cultural"},
        {"date": "2023-01-31", "type": "than_tai", "title": "Ngày vía Thần Tài Quý Mão 2023: Khách xếp hàng từ sáng sớm, spread mua-bán nới rộng", "category": "cultural"},
        {"date": "2022-02-24", "type": "geopolitical_crisis", "title": "Chiến sự Nga - Ukraina bùng phát, giá vàng thế giới vượt 2.000 USD/oz, SJC lập đỉnh mới", "category": "global"},
        {"date": "2020-03-16", "type": "financial_crisis", "title": "Khủng hoảng đại dịch COVID-19 toàn cầu: Fed hạ lãi suất khẩn cấp về 0%, bơm thanh khoản kỷ lục", "category": "global"},
        {"date": "2013-03-28", "type": "policy_auction", "title": "Phiên đấu thầu vàng miếng SJC đầu tiên trong lịch sử do NHNN tổ chức", "category": "policy"},
        {"date": "2012-04-03", "type": "sbv_policy", "title": "Chính phủ ban hành Nghị định 24/2012/NĐ-CP: Nhà nước độc quyền sản xuất vàng miếng, SJC thành thương hiệu quốc gia", "category": "policy"},
        {"date": "2011-08-23", "type": "gold_price_up", "title": "Đỉnh giá vàng chu kỳ trước: SJC chạm mốc 49 triệu VND/lượng, thế giới đạt 1.920 USD/oz", "category": "price_move"},
    ]

    seen_event_keys = set()
    for cm in curated_milestones:
        seen_event_keys.add((cm["date"], cm["title"][:30]))
        events.append(cm)

    if events_file.exists():
        raw_events = load_csv(events_file)
        for ev in raw_events:
            edate = ev.get("event_date")
            etype = ev.get("event_type") or "other"
            note = ev.get("note") or etype
            channel = ev.get("expected_channel") or ""

            # Filter out continuous daily repetitions of wedding
            if "wedding_season" in etype or "tet_proximity" in etype:
                continue
            if not edate or edate < "2011-01-01":
                continue

            # Determine user-friendly category
            category = "other"
            if any(k in etype for k in ["policy", "sbv", "auction", "import", "inspection"]):
                category = "policy"
            elif any(k in etype for k in ["price_up", "price_down", "price_move"]):
                category = "price_move"
            elif "fx" in etype:
                category = "fx"
            elif any(k in etype for k in ["crisis", "global", "geopolitical", "fed", "macro_shock", "stress"]):
                category = "global"
            elif any(k in etype for k in ["than_tai", "god_of_wealth", "tet"]):
                category = "cultural"

            key = (edate, note[:30])
            if key not in seen_event_keys:
                seen_event_keys.add(key)
                events.append({
                    "date": edate,
                    "type": etype,
                    "title": note,
                    "channel": channel,
                    "category": category,
                    # URL giúp người xem truy về bản tin; proxy không được
                    # trình bày như quyết định chính thức của NHNN.
                    "source_url": ev.get("source_url") or "",
                    "is_proxy": ev.get("source") == "google_news_rss_event_proxy",
                })

    # Sort events DESCENDING: Newest first (2026 -> 2025 -> 2024 -> ... -> 2011)
    events.sort(key=lambda x: x["date"], reverse=True)

    # Summary metrics
    latest_row = timeline[-1] if timeline else {}
    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_records": len(timeline),
        "start_date": timeline[0]["d"] if timeline else "",
        "end_date": latest_row.get("d", ""),
        "latest_sell": latest_row.get("s"),
        "latest_buy": latest_row.get("b"),
        "latest_spread": latest_row.get("sp"),
        "latest_global_usd": latest_row.get("gu"),
        "latest_global_vnd": latest_row.get("gv") or (latest_valid_premium["global_vnd"] if latest_valid_premium else None),
        "latest_premium": latest_row.get("p") or (latest_valid_premium["premium"] if latest_valid_premium else None),
        "latest_premium_pct": latest_row.get("pp") or (latest_valid_premium["premium_pct"] if latest_valid_premium else None),
        "latest_fx": latest_row.get("fx"),
        "ath_premium": round(ath_premium, 0),
        "ath_premium_date": ath_premium_date,
    }

    recommendations = build_recommendations(lake, expected_snapshot_date=summary["end_date"])

    out_file = out_dir / "gold_dashboard_data.json"
    data_payload = {
        "summary": summary,
        "recommendations": recommendations,
        "timeline": timeline,
        "events": events[:1000],  # comprehensive events across 2011-2026
    }

    out_file.write_text(json.dumps(data_payload, ensure_ascii=False, separators=(',', ':')), encoding="utf-8")
    size_kb = out_file.stat().st_size / 1024
    print(f"Saved {len(timeline)} records ({size_kb:.1f} KB) to {out_file} (recommendations included: {bool(recommendations)})")


if __name__ == "__main__":
    main()
