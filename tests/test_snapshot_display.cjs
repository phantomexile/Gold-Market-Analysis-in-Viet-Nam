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
  });
  renderDecisionSupport();
`, context);
assert.equal(elements.execActionText.textContent, 'BÁN');
assert.match(elements.execBadge.textContent, /3 tháng/);
assert.match(elements.horizonGrid.innerHTML, /<div class="signal-details">/);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /<details|<summary/);
assert.match(elements.horizonGrid.innerHTML, /Chi tiết dự báo/);
assert.match(elements.horizonGrid.innerHTML, /Rủi ro Q10/);
assert.match(elements.horizonGrid.innerHTML, /Nếu đang giữ vàng/);
assert.match(elements.horizonGrid.innerHTML, /Lý do đề xuất/);
assert.equal((elements.horizonGrid.innerHTML.match(/Nếu đang giữ vàng/g) || []).length, 1);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /Đánh giá lịch sử|Kiểm chứng thực tế|dự báo đáo hạn/);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /Mô phỏng nghiên cứu: có tín hiệu tích lũy/);
vm.runInContext(`
  state.data.recommendations.horizons[0].rationale = '<img src=x onerror=alert(1)> & mô hình';
  renderDecisionSupport();
`, context);
assert.doesNotMatch(elements.horizonGrid.innerHTML, /<img\s/);
assert.match(elements.horizonGrid.innerHTML, /&lt;img/);
console.log('Tín hiệu trực tiếp hiển thị sẵn Chi tiết dự báo và hỗ trợ Bán.');
