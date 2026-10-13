#!/usr/bin/env python3
"""
Prepares optimized JSON dataset for the Gold Market Visualizer Dashboard.
Reads from data/lake/ and outputs to web/data/gold_dashboard_data.json.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_recommendations(lake: Path) -> dict:
    snapshot_path = lake / "modeling" / "snapshot_forecasts.csv"
    if not snapshot_path.exists():
        return {}

    rows = load_csv(snapshot_path)
    if not rows:
        return {}

    snapshot_date = rows[0].get("snapshot_date", "")
    horizons_data = []

    for r in rows:
        try:
            h_days = int(r.get("horizon_days", 0))
            h_label = r.get("horizon_label", f"{h_days}d")
            pred_ret = float(r.get("predicted_net_return", 0))
            q10_ret = float(r.get("q10_predicted_net_return", 0))
            prob_pos = float(r.get("prob_return_positive", 0))
            buy_sig = r.get("buy_signal", "").lower() in ("true", "1")
        except (ValueError, TypeError):
            continue

        action = "Mua tích lũy" if buy_sig else "Không mua mới"
        badge_type = "positive" if buy_sig else "negative"

        pred_pct = round(pred_ret * 100, 2)
        q10_pct = round(q10_ret * 100, 2)
        prob_pct = round(prob_pos * 100, 1)

        # Calibration for 63d (as in build_full_report.py)
        if h_days == 63:
            if pred_ret <= 0 or q10_ret < -0.10:
                action = "Không mua mới"
                badge_type = "warning"

        if h_days == 21:
            horizon_desc = "1 Tháng (21 phiên)"
            if buy_sig:
                rationale = f"Tín hiệu mua ngắn hạn kích hoạt; kỳ vọng LN ròng {pred_pct:+.2f}%, xác suất sinh lời {prob_pct:.1f}%."
            else:
                rationale = f"Spread Mua - Bán (~3 triệu ₫) bào mòn tỷ suất; LN ròng dự báo {pred_pct:+.2f}%, xác suất sinh lời chỉ {prob_pct:.1f}%."
        elif h_days == 63:
            horizon_desc = "3 Tháng (63 phiên)"
            if buy_sig:
                rationale = f"Tín hiệu trung hạn tích cực; kỳ vọng LN ròng {pred_pct:+.2f}%, rủi ro sụt giảm Q10 ở mức an toàn {q10_pct:+.2f}%."
            else:
                rationale = f"Kỳ vọng LN ròng {pred_pct:+.2f}%, rủi ro sụt giảm Q10 ({q10_pct:+.2f}%) vượt ngưỡng an toàn, xác suất sinh lời {prob_pct:.1f}%."
        elif h_days == 105:
            horizon_desc = "5 Tháng (105 phiên)"
            if buy_sig:
                rationale = f"Tín hiệu tích lũy dài hạn; kỳ vọng LN ròng {pred_pct:+.2f}%, xác suất sinh lời {prob_pct:.1f}%, hấp thu tốt spread."
            else:
                rationale = f"SJC neo ở vùng đỉnh lịch sử (Premium >40 triệu ₫); mô hình cảnh báo rủi ro điều chỉnh {pred_pct:+.2f}%, xác suất lãi {prob_pct:.1f}%."
        else:
            horizon_desc = f"{h_label} ({h_days} phiên)"
            rationale = f"Kỳ vọng LN ròng {pred_pct:+.2f}%, rủi ro đuôi Q10 {q10_pct:+.2f}%, xác suất thắng {prob_pct:.1f}%."

        horizons_data.append({
            "horizon_days": h_days,
            "horizon_label": horizon_desc,
            "predicted_net_return": pred_pct,
            "q10_predicted_net_return": q10_pct,
            "prob_return_positive": prob_pct,
            "buy_signal": buy_sig,
            "action": action,
            "badge_type": badge_type,
            "rationale": rationale,
        })

    horizons_data.sort(key=lambda x: x["horizon_days"])

    has_5m_buy = any(h["horizon_days"] == 105 and h["action"] == "Mua tích lũy" for h in horizons_data)
    has_1m_buy = any(h["horizon_days"] == 21 and h["action"] == "Mua tích lũy" for h in horizons_data)

    if has_5m_buy:
        h5 = next(h for h in horizons_data if h["horizon_days"] == 105)
        primary_action = "MUA TÍCH LŨY CÓ KIỂM SOÁT (5 THÁNG)"
        action_theme = "positive"
        executive_summary = (
            f"Khuyến nghị chính: Có thể xem xét mua tích lũy có kiểm soát cho tầm nhìn khoảng 5 tháng "
            f"(kỳ vọng lợi nhuận ròng {h5['predicted_net_return']:+.2f}% sau khi đã trừ chi phí chênh lệch spread SJC). "
            "Tuyệt đối KHÔNG mua đuổi quy mô lớn một lần. Kỳ hạn 1 & 3 tháng chưa có tín hiệu mua do áp lực spread và rủi ro sụt giảm ngắn hạn."
        )
    elif has_1m_buy:
        primary_action = "GIAO DỊCH NGẮN HẠN NHỎ (1 THÁNG)"
        action_theme = "warning"
        executive_summary = (
            "Khuyến nghị chính: Chỉ giao dịch tỷ trọng nhỏ ngắn hạn nếu chấp nhận rủi ro, chưa đủ bằng chứng để tích lũy dài hạn 3-5 tháng."
        )
    else:
        primary_action = "KHÔNG MUA MỚI / QUAN SÁT THỊ TRƯỜNG"
        action_theme = "negative"
        executive_summary = (
            f"Khuyến nghị chính (Snapshot {snapshot_date}): KHÔNG MỞ VỊ THẾ MUA MỚI ở tất cả các kỳ hạn (1, 3, 5 tháng). "
            "Giá vàng SJC hiện đang neo quanh vùng đỉnh lịch sử (144 triệu ₫/lượng) với mức chênh lệch nội - ngoại (SJC Premium) kỷ lục trên 41 triệu ₫/lượng. "
            "Mô hình học máy dự báo xác suất sinh lời ròng sau spread rất thấp (<5%) và rủi ro đảo chiều điều chỉnh cao. "
            "Ưu tiên giữ vị thế tiền mặt và chờ đợi các phiên điều chỉnh kỹ thuật hoặc can thiệp bình ổn từ Ngân hàng Nhà nước."
        )

    return {
        "snapshot_date": snapshot_date,
        "primary_action": primary_action,
        "action_theme": action_theme,
        "executive_summary": executive_summary,
        "horizons": horizons_data,
        "rules_explained": [
            "Khấu trừ Spread thực tế: Toàn bộ lợi nhuận ròng đã trừ chênh lệch Mua - Bán của SJC (~3.000.000 ₫/lượng).",
            "Bộ lọc rủi ro đuôi Quantile Q10: Chỉ mở vị thế khi P(lãi) ≥ 50% và rủi ro sụt giảm kịch bản xấu nhất Q10 ≥ -10%.",
            "Mô hình học máy: Kết hợp Random Forest & Gradient Boosting Quantile trên 5.400+ phiên giao dịch (2010 - 2026)."
        ]
    }


def main():
    root = Path(__file__).resolve().parent.parent
    lake = root / "data" / "lake"
    out_dir = root / "web" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    enriched_file = lake / "gold_prices" / "gold_daily_enriched.csv"
    if not enriched_file.exists():
        enriched_file = lake / "gold_daily_enriched.csv"

    events_file = lake / "event_regime_panel.csv"

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
        {"date": "2026-10-06", "type": "gold_price_move", "title": "Giá vàng SJC duy trì mốc 142.9 triệu VND/lượng, chênh lệch nội - ngoại quanh 41.5 triệu VND", "category": "price_move"},
        {"date": "2026-09-30", "type": "macro_shock", "title": "SJC chốt quý 3/2026 ở mức 144.1 triệu VND/lượng; vàng thế giới neo trên 4.150 USD/oz", "category": "global"},
        {"date": "2026-08-15", "type": "sbv_policy", "title": "Thị trường vàng trong nước ổn định biên độ; NHNN tiếp tục theo dõi sát tỷ giá và giá vàng", "category": "policy"},
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

    recommendations = build_recommendations(lake)

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
