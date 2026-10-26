/** Dự báo thiếu xác suất phải hiển thị rõ và không làm hỏng dashboard. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const elements = {};
const context = vm.createContext({
  document: {
    addEventListener() {},
    getElementById(id) {
      return elements[id] ||= { style: {}, textContent: '', innerHTML: '' };
    },
  },
  console,
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/js/app.js'), 'utf8'), context);
// Dùng hàm hiển thị thật với JSON có null, giống snapshot thiếu hiệu chỉnh ngoài mẫu.
vm.runInContext(`
  state.data = { recommendations: {
    snapshot_date: '2026-10-24', primary_signal: 'observe', action_theme: 'warning',
    primary_action: 'KHÔNG MUA MỚI / QUAN SÁT THỊ TRƯỜNG',
    horizons: [{ horizon_label: '3 tháng', badge_type: 'warning', action: 'Quan sát',
      predicted_net_return: null, q10_predicted_net_return: null, prob_return_positive: null,
      rationale: 'Chưa đủ sai số dự báo ngoài mẫu.' }],
  }};
  renderDecisionSupport();
`, context);
assert.match(elements.horizonGrid.innerHTML, /Chưa đủ dữ liệu/);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /(?:NaN|undefined|null)%/);
assert.equal(elements.execBadge.textContent, 'Thận trọng');
// Nguyên nhân lỗi kiểm định có thể chứa dữ liệu tệp; phải hiển thị như văn bản.
vm.runInContext(`
  state.data.recommendations.horizons[0].rationale = '<img src=x onerror=alert(1)> & kiểm định';
  renderDecisionSupport();
`, context);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /<img\s/);
assert.match(elements.horizonGrid.innerHTML, /&lt;img/);
// Metadata kiểm định không chiếm thẻ tín hiệu; thẻ giải thích lý do đề xuất.
vm.runInContext(`
  Object.assign(state.data.recommendations.horizons[0], {
    simulation_buy_signal: true,
    historical: { label: 'Đạt đánh giá lịch sử', status: 'historical_passed',
      metrics: { mae: 0.02, zero_baseline_mae: 0.04 }, notice: 'Chỉ phục vụ nghiên cứu.' },
    prospective: { label: 'Đang tích lũy bằng chứng thực tế', status: 'validation_pending',
      metrics: { matured_rows: 12, nonoverlapping_windows: 1, origin_span_days: 30 },
      targets: { min_matured_rows: 120, min_nonoverlapping_windows: 6, min_origin_span_days: 365 } },
  });
  renderDecisionSupport();
`, context);
assert.match(elements.horizonGrid.innerHTML, /Lý do đề xuất/);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /Đánh giá lịch sử|Kiểm chứng thực tế|Mô phỏng nghiên cứu/);
assert.match(elements.execActionText.textContent, /QUAN SÁT/);
console.log('Dashboard hiển thị dự báo thiếu số liệu an toàn.');

// Chế độ trực tiếp hiển thị sẵn lý do và số liệu, không cần bấm mục thu gọn.
vm.runInContext(`
  Object.assign(state.data.recommendations, {
    signal_mode: 'direct_forecast', primary_horizon_months: 3,
    primary_signal: 'sell', primary_action: 'BÁN', action_theme: 'negative',
  });
  Object.assign(state.data.recommendations.horizons[0], {
    signal: 'sell', action: 'Bán', badge_type: 'negative', predicted_net_return: -5,
    predicted_hold_return: -3, rationale: 'Nếu đang giữ vàng, cân nhắc bán.',
    calibration_note: 'Brier chưa tốt hơn baseline. Pinball của Q10 chưa đạt.',
  });
  renderDecisionSupport();
`, context);
assert.equal(elements.execActionText.textContent, 'BÁN');
assert.match(elements.execBadge.textContent, /3 tháng/);
assert.match(elements.horizonGrid.innerHTML, /<div class="signal-details">/);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /<details|<summary/);
assert.match(elements.horizonGrid.innerHTML, /Chi tiết dự báo/);
assert.match(elements.horizonGrid.innerHTML, /Nếu mua vàng hôm nay/);
assert.match(elements.horizonGrid.innerHTML, /Nếu đang có vàng/);
assert.match(elements.horizonGrid.innerHTML, /Kịch bản xấu \(Q10\)/);
assert.match(elements.horizonGrid.innerHTML, /Khả năng có lãi/);
assert.match(elements.horizonGrid.innerHTML, /Chưa có số ước tính mức lãi\/lỗ/);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /Brier|Pinball|baseline/);
assert.match(elements.horizonGrid.innerHTML, /Nếu đang giữ vàng/);
assert.match(elements.horizonGrid.innerHTML, /Lý do đề xuất/);
assert.equal((elements.horizonGrid.innerHTML.match(/Nếu đang giữ vàng/g) || []).length, 1);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /Đánh giá lịch sử|Kiểm chứng thực tế|dự báo đáo hạn/);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /Mô phỏng nghiên cứu: có tín hiệu tích lũy/);
vm.runInContext(`
  state.data.recommendations.horizons[0].horizon_label = '<img src=x onerror=alert(1)> & mô hình';
  renderDecisionSupport();
`, context);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /<img\s/);
assert.match(elements.horizonGrid.innerHTML, /&lt;img/);
console.log('Tín hiệu trực tiếp hiển thị sẵn Chi tiết dự báo và hỗ trợ Bán.');

// Chỉ làm nổi bật kỳ hạn có lãi dự báo cao nhất; giữ gợi ý mặc định của máy chủ.
vm.runInContext(`
  state.data.recommendations = {
    signal_mode: 'direct_forecast', primary_horizon_months: 3,
    primary_action: 'MUA', action_theme: 'positive',
    horizons: [
      { horizon_months: 1, horizon_label: '1 tháng', signal: 'observe', action: 'Quan sát', badge_type: 'warning', predicted_net_return: -0.66 },
      { horizon_months: 3, horizon_label: '3 tháng', signal: 'buy', action: 'Mua', badge_type: 'positive', predicted_net_return: 3.08 },
      { horizon_months: 5, horizon_label: '5 tháng', signal: 'buy', action: 'Mua', badge_type: 'positive', predicted_net_return: 8.47 }
    ]
  };
  renderDecisionSupport();
`, context);
assert.match(elements.execHeading.textContent, /3 tháng/);
assert.match(elements.execSummaryText.textContent, /3,08%/);
assert.equal((elements.horizonGrid.innerHTML.match(/Lãi dự báo cao nhất/g) || []).length, 1);
assert.match(elements.horizonGrid.innerHTML, /5 tháng<\/span>[\s\S]*?Lãi dự báo cao nhất/);
assert.match(elements.horizonGrid.innerHTML, /horizon-card[^\"]*highest-return-card/);
assert.doesNotMatch(fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8'), /decisionHorizonSelector|Bạn muốn xem kỳ hạn nào/);
// Không gắn nhãn lãi cao nhất nếu mọi dự báo đều lỗ hoặc thiếu số liệu.
vm.runInContext(`
  state.data.recommendations.horizons.forEach(h => h.predicted_net_return = null);
  state.data.recommendations.horizons[0].predicted_net_return = -1;
  renderDecisionSupport();
`, context);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /Lãi dự báo cao nhất/);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /highest-return-card/);
console.log('Thẻ lãi dự báo cao nhất được làm nổi bật, không còn bộ chọn kỳ hạn.');

// CSS và JavaScript cần cùng phiên bản mới để tránh hiển thị nhãn mới bằng CSS cũ.
const dashboardHtml = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
assert.match(dashboardHtml, /css\/style\.css\?v=20261026-raw-estimates/);
assert.match(dashboardHtml, /js\/app\.js\?v=20261026-raw-estimates/);

// Hiển thị số ước tính gốc dù chỉ số công bố sau kiểm định còn null.
vm.runInContext(`
  Object.assign(state.data.recommendations.horizons[1], {
    q10_predicted_net_return: null, prob_return_positive: null,
    research_q10_predicted_net_return: -12.34, research_prob_return_positive: 62.43,
  });
  renderDecisionSupport();
`, context);
assert.match(elements.horizonGrid.innerHTML, /-12,34%/);
assert.match(elements.horizonGrid.innerHTML, /62,43%/);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /chưa đủ tin cậy để hiển thị thành số/);
