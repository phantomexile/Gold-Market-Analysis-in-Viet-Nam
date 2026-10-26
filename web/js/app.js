/**
 * VN Gold Intelligence Terminal - Interactive Visualization Engine
 */

let state = {
  data: null,
  activeRange: '1Y',
  activeTab: 'divergence',
  chartInstance: null,
  filteredTimeline: [],
  tablePage: 1,
  tablePageSize: 15,
  searchQuery: '',
  updateRunning: false,
};

// Formatting Helpers
const fmtCurrency = (val) => {
  if (val === null || val === undefined || isNaN(val)) return '—';
  return new Intl.NumberFormat('vi-VN').format(Math.round(val)) + ' ₫';
};

const fmtMillions = (val) => {
  if (val === null || val === undefined || isNaN(val)) return '—';
  return (val / 1000000).toFixed(2) + ' tr ₫';
};

const fmtUSD = (val) => {
  if (val === null || val === undefined || isNaN(val)) return '—';
  return '$' + new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(val);
};

const fmtPct = (val) => {
  if (val === null || val === undefined || isNaN(val)) return '—';
  const prefix = val > 0 ? '+' : '';
  return `${prefix}${val.toFixed(2)}%`;
};

// Initialize Application
document.addEventListener('DOMContentLoaded', async () => {
  setupEventListeners();
  await loadData();
  await restoreUpdateProgress();
});

function setupEventListeners() {
  // Time Range Buttons
  document.querySelectorAll('.range-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('.range-btn').forEach((b) => b.classList.remove('active'));
      e.target.classList.add('active');
      state.activeRange = e.target.dataset.range;
      filterDataByRange();
      renderCurrentChart();
      renderDataTable();
      renderEventList();
    });
  });

  // View Switcher Tabs
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
      e.currentTarget.classList.add('active');
      state.activeTab = e.currentTarget.dataset.tab;
      renderCurrentChart();
    });
  });

  // Table Search
  const searchInput = document.getElementById('tableSearch');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      state.searchQuery = e.target.value.trim().toLowerCase();
      state.tablePage = 1;
      renderDataTable();
    });
  }

  // Table Pagination
  const prevBtn = document.getElementById('prevPageBtn');
  const nextBtn = document.getElementById('nextPageBtn');
  if (prevBtn) prevBtn.addEventListener('click', () => changePage(-1));
  if (nextBtn) nextBtn.addEventListener('click', () => changePage(1));

  // Action Buttons
  const refreshBtn = document.getElementById('btnRefreshData');
  if (refreshBtn) refreshBtn.addEventListener('click', handleLiveUpdate);

  const exportBtn = document.getElementById('btnExportCsv');
  if (exportBtn) exportBtn.addEventListener('click', exportCsv);
}

async function loadData() {
  try {
    showToast('Đang tải dữ liệu chuỗi thời gian...', '⏳');
    // Try API first, fallback to static JSON
    let response;
    try {
      response = await fetch('/api/data', { cache: 'no-store' });
      if (!response.ok) throw new Error();
    } catch {
      response = await fetch('data/gold_dashboard_data.json', { cache: 'no-store' });
    }

    if (!response.ok) throw new Error('Không thể tải file dữ liệu');
    state.data = await response.json();
    
    updateKpiCards();
    renderDecisionSupport();
    updateStatisticsPanel();
    renderEventList();
    filterDataByRange();
    renderCurrentChart();
    renderDataTable();
    showToast(`Tải thành công ${state.data.summary.total_records.toLocaleString('vi-VN')} phiên giao dịch vàng!`, '✨');
  } catch (err) {
    console.error('Error loading data:', err);
    showToast('Lỗi nạp dữ liệu: ' + err.message, '❌');
  }
}

function renderDecisionSupport() {
  const rec = state.data.recommendations;
  const sec = document.getElementById('decisionSupportSection');
  if (!rec || !rec.horizons || rec.horizons.length === 0) {
    if (sec) sec.style.display = 'none';
    return;
  }
  if (sec) sec.style.display = 'block';

  // Snapshot date
  const snapshotDateEl = document.getElementById('decisionSnapshotDate');
  if (snapshotDateEl && rec.snapshot_date) {
    snapshotDateEl.textContent = `Snapshot: ${rec.snapshot_date}`;
  }

  // Executive Signal Box
  const execBox = document.getElementById('execSignalBox');
  const execAction = document.getElementById('execActionText');
  const execBadge = document.getElementById('execBadge');
  const execText = document.getElementById('execSummaryText');

  if (execBox && execAction) {
    execBox.className = 'exec-signal-box ' + (rec.action_theme || 'positive');
    execAction.textContent = rec.primary_action || 'QUAN SÁT THỊ TRƯỜNG';
  }
  if (execBadge) {
    execBadge.textContent = rec.signal_mode === 'direct_forecast'
      ? `${rec.primary_horizon_months || 3} tháng • ${rec.primary_model_label || 'Dự báo mô hình'}`
      : (rec.action_theme === 'positive' ? 'Khuyến nghị Tích lũy' : (rec.action_theme === 'warning' ? 'Thận trọng' : 'Quan sát'));
  }
  if (execText && rec.executive_summary) {
    execText.textContent = rec.executive_summary;
  }

  // Horizon Cards
  const gridEl = document.getElementById('horizonGrid');
  if (gridEl) {
    // Lý do kiểm định có thể chứa tên tệp hoặc dữ liệu lỗi; hiển thị nguyên
    // văn tiếng Việt, không để nội dung đó trở thành HTML có thể thực thi.
    const safeText = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[character]);
    if (rec.signal_mode === 'direct_forecast') {
      // Tín hiệu do backend tính theo dự báo; không dùng kiểm định/P/Q10 để
      // đổi quyết định trên trình duyệt. Số liệu hiển thị sẵn dưới lý do để
      // người xem đối chiếu ngay, không cần mở một mục thu gọn.
      const pct = (value) => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : 'Chưa đủ dữ liệu';
      gridEl.innerHTML = rec.horizons.map((h) => {
        return `
          <div class="horizon-card direct-signal-card ${safeText(h.badge_type || 'warning')}">
            <div class="horizon-header">
              <span class="horizon-title">${safeText(h.horizon_label)}</span>
              <span class="action-pill ${safeText(h.badge_type || 'warning')}">${safeText(h.action || 'Quan sát')}</span>
            </div>
            <div class="signal-reason">
              <div class="assessment-title">Lý do đề xuất</div>
              <p class="direct-signal-reason">${safeText(h.rationale || 'Chưa có đủ dữ liệu để giải thích tín hiệu.')}</p>
            </div>
            <div class="signal-details">
              <div class="assessment-title">Chi tiết dự báo</div>
              <div class="horizon-metrics direct-metrics">
                <div class="h-metric"><span class="h-metric-label">Lợi suất mua mới</span><span class="h-metric-val">${pct(h.predicted_net_return)}</span></div>
                <div class="h-metric"><span class="h-metric-label">Giữ thêm so với bán ngay</span><span class="h-metric-val">${pct(h.predicted_hold_return)}</span></div>
                <div class="h-metric"><span class="h-metric-label">Rủi ro Q10</span><span class="h-metric-val">${pct(h.q10_predicted_net_return)}</span></div>
                <div class="h-metric"><span class="h-metric-label">Xác suất lãi ước lượng</span><span class="h-metric-val">${pct(h.prob_return_positive)}</span></div>
              </div>
            </div>
          </div>`;
      }).join('');
      return;
    }
    gridEl.innerHTML = rec.horizons.map((h) => {
      // Snapshot thiếu hiệu chỉnh trả null thay vì bịa xác suất; không gọi
      // toFixed trên null và không tô màu xanh cho số liệu chưa tồn tại.
      const hasReturn = Number.isFinite(h.predicted_net_return);
      const hasQ10 = Number.isFinite(h.q10_predicted_net_return);
      const hasProbability = Number.isFinite(h.prob_return_positive);
      const retClass = hasReturn && h.predicted_net_return > 0 ? 'positive' : (hasReturn && h.predicted_net_return < 0 ? 'negative' : 'warning');
      const q10Class = !hasQ10 ? 'warning' : (h.q10_predicted_net_return >= -10 ? 'positive' : 'negative');
      const probClass = !hasProbability ? 'warning' : (h.prob_return_positive >= 50 ? 'positive' : 'negative');
      // Cả JSON cũ và chế độ trực tiếp cùng giải thích tín hiệu bằng rationale;
      // không lặp lại các bảng kiểm định/mô phỏng trong thẻ đề xuất.

      return `
        <div class="horizon-card ${h.badge_type}">
          <div class="horizon-header">
            <span class="horizon-title">${safeText(h.horizon_label)}</span>
            <span class="action-pill ${h.badge_type}">${safeText(h.action)}</span>
          </div>
          <div class="horizon-metrics">
            <div class="h-metric">
              <span class="h-metric-label">LN Ròng Dự Báo</span>
              <span class="h-metric-val ${retClass}">${hasReturn ? `${h.predicted_net_return > 0 ? '+' : ''}${h.predicted_net_return.toFixed(2)}%` : 'Chưa đủ dữ liệu'}</span>
            </div>
            <div class="h-metric">
              <span class="h-metric-label">Rủi Ro Đuôi Q10</span>
              <span class="h-metric-val ${q10Class}">${hasQ10 ? `${h.q10_predicted_net_return > 0 ? '+' : ''}${h.q10_predicted_net_return.toFixed(2)}%` : 'Chưa đủ dữ liệu'}</span>
            </div>
            <div class="h-metric">
              <span class="h-metric-label">Xác Suất Lãi P(>0)</span>
              <span class="h-metric-val ${probClass}">${hasProbability ? `${h.prob_return_positive.toFixed(1)}%` : 'Chưa đủ dữ liệu'}</span>
            </div>
          </div>
          <div class="signal-reason">
            <div class="assessment-title">Lý do đề xuất</div>
            <p class="direct-signal-reason">${safeText(h.rationale || 'Chưa có đủ dữ liệu để giải thích tín hiệu.')}</p>
          </div>
        </div>
      `;
    }).join('');
  }
}

function updateKpiCards() {
  const s = state.data.summary;
  const timeline = state.data.timeline;
  if (!timeline || timeline.length === 0) return;

  const latest = timeline[timeline.length - 1];
  const prev = timeline.length > 1 ? timeline[timeline.length - 2] : latest;

  // SJC Sell
  document.getElementById('kpiSellPrice').textContent = fmtMillions(latest.s);
  const sellDiff = (latest.s || 0) - (prev.s || 0);
  const sellDiffEl = document.getElementById('kpiSellChange');
  if (sellDiffEl) {
    sellDiffEl.className = 'kpi-change ' + (sellDiff >= 0 ? 'positive' : 'negative');
    sellDiffEl.textContent = (sellDiff >= 0 ? '▲ ' : '▼ ') + fmtMillions(Math.abs(sellDiff)) + ' (24h)';
  }

  // SJC Buy
  document.getElementById('kpiBuyPrice').textContent = fmtMillions(latest.b);

  // Spread
  document.getElementById('kpiSpread').textContent = fmtMillions(latest.sp);
  const spreadPctEl = document.getElementById('kpiSpreadPct');
  if (spreadPctEl && latest.s && latest.sp) {
    const spPct = (latest.sp / latest.s) * 100;
    spreadPctEl.textContent = `Tỷ lệ: ${spPct.toFixed(2)}%`;
  }

  // Global Gold in VND
  document.getElementById('kpiGlobalVnd').textContent = fmtMillions(s.latest_global_vnd);
  document.getElementById('kpiGlobalUsd').textContent = fmtUSD(latest.gu) + ' / toz';

  // Premium
  document.getElementById('kpiPremium').textContent = fmtMillions(s.latest_premium);
  const premPctEl = document.getElementById('kpiPremiumPct');
  if (premPctEl) {
    premPctEl.className = 'kpi-change ' + (s.latest_premium >= 0 ? 'positive' : 'negative');
    premPctEl.textContent = fmtPct(s.latest_premium_pct);
  }

  // USD/VND Exchange Rate
  document.getElementById('kpiUsdVnd').textContent = fmtCurrency(latest.fx);
  document.getElementById('lastUpdatedBadge').textContent = `Cập nhật: ${latest.d}`;
}

function filterDataByRange() {
  const full = state.data.timeline;
  if (!full || full.length === 0) return;

  if (state.activeRange === 'ALL') {
    state.filteredTimeline = [...full];
    return;
  }

  const latestDate = new Date(full[full.length - 1].d);
  let cutoff = new Date(latestDate);

  switch (state.activeRange) {
    case '1M':
      cutoff.setMonth(cutoff.getMonth() - 1);
      break;
    case '3M':
      cutoff.setMonth(cutoff.getMonth() - 3);
      break;
    case '6M':
      cutoff.setMonth(cutoff.getMonth() - 6);
      break;
    case '1Y':
      cutoff.setFullYear(cutoff.getFullYear() - 1);
      break;
    case '3Y':
      cutoff.setFullYear(cutoff.getFullYear() - 3);
      break;
    case '5Y':
      cutoff.setFullYear(cutoff.getFullYear() - 5);
      break;
  }

  const cutoffStr = cutoff.toISOString().slice(0, 10);
  state.filteredTimeline = full.filter((item) => item.d >= cutoffStr);
}

function renderCurrentChart() {
  const ctx = document.getElementById('mainChartCanvas').getContext('2d');
  if (state.chartInstance) {
    state.chartInstance.destroy();
  }

  const rows = state.filteredTimeline;
  const labels = rows.map((r) => r.d);

  const titleEl = document.getElementById('chartTitle');
  const subEl = document.getElementById('chartSubtitle');

  let chartConfig = null;

  switch (state.activeTab) {
    case 'divergence':
      titleEl.innerHTML = '📊 So Sánh Giá Vàng Trong Nước (SJC) vs Quốc Tế Quy Đổi';
      subEl.textContent = 'Phản ánh mức độ tách rời (decoupling) giữa vàng vật chất Việt Nam và giá thế giới (VND/lượng).';
      chartConfig = createDivergenceConfig(labels, rows);
      break;

    case 'premium':
      titleEl.innerHTML = '🔥 Phân Rã Chênh Lệch Giá (SJC Domestic Premium)';
      subEl.textContent = 'Khoảng chênh tuyệt đối (triệu VND/lượng) và tỷ lệ chênh lệch (%) so với giá vàng thế giới.';
      chartConfig = createPremiumConfig(labels, rows);
      break;

    case 'spread':
      titleEl.innerHTML = '⚖️ Chênh Lệch Giá Mua - Giá Bán (Bid-Ask Spread) & Rủi Ro Thanh Khoản';
      subEl.textContent = 'Biến động spread phản ánh rủi ro thị trường và biến động cung cầu trong các giai đoạn cao điểm.';
      chartConfig = createSpreadConfig(labels, rows);
      break;

    case 'macro':
      titleEl.innerHTML = '🌐 Tương Quan Giá Vàng Với Tỷ Giá USD/VND & Vàng Thế Giới (GC=F)';
      subEl.textContent = 'Đa trục phân tích động lực truyền dẫn từ tỷ giá hối đoái và vàng tương lai New York.';
      chartConfig = createMacroConfig(labels, rows);
      break;
  }

  if (chartConfig) {
    state.chartInstance = new Chart(ctx, chartConfig);
  }
}

/* Chart Configurations */
function createDivergenceConfig(labels, rows) {
  return {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'SJC Bán ra (VND/lượng)',
          data: rows.map((r) => (r.s ? r.s / 1000000 : null)),
          borderColor: '#f59e0b',
          backgroundColor: 'rgba(245, 158, 11, 0.1)',
          borderWidth: 2.2,
          pointRadius: 0,
          pointHoverRadius: 5,
          tension: 0.1,
          fill: false,
          spanGaps: true,
        },
        {
          label: 'SJC Mua vào (VND/lượng)',
          data: rows.map((r) => (r.b ? r.b / 1000000 : null)),
          borderColor: '#d97706',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0,
          fill: false,
          spanGaps: true,
        },
        {
          label: 'Vàng Thế Giới quy đổi (VND/lượng)',
          data: rows.map((r) => (r.gv ? r.gv / 1000000 : null)),
          borderColor: '#06b6d4',
          backgroundColor: 'rgba(6, 182, 212, 0.05)',
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 5,
          tension: 0.1,
          fill: false,
          spanGaps: true,
        },
      ],
    },
    options: getBaseChartOptions('Triệu VND / Lượng'),
  };
}

function createPremiumConfig(labels, rows) {
  return {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Premium Tuyệt Đối (Triệu VND/lượng)',
          data: rows.map((r) => (r.p !== null ? r.p / 1000000 : null)),
          borderColor: '#f59e0b',
          backgroundColor: (context) => {
            const ctx = context.chart.ctx;
            const gradient = ctx.createLinearGradient(0, 0, 0, 400);
            gradient.addColorStop(0, 'rgba(245, 158, 11, 0.45)');
            gradient.addColorStop(1, 'rgba(245, 158, 11, 0.0)');
            return gradient;
          },
          borderWidth: 2.5,
          pointRadius: 0,
          pointHoverRadius: 5,
          fill: true,
          tension: 0.15,
          spanGaps: true,
          yAxisID: 'y',
        },
        {
          label: 'Premium Tương Đối (%)',
          data: rows.map((r) => r.pp),
          borderColor: '#a855f7',
          borderWidth: 1.8,
          borderDash: [3, 3],
          pointRadius: 0,
          pointHoverRadius: 4,
          fill: false,
          spanGaps: true,
          yAxisID: 'y1',
        },
      ],
    },
    options: {
      ...getBaseChartOptions('Triệu VND / Lượng'),
      scales: {
        ...getBaseChartOptions().scales,
        y: {
          ...getBaseChartOptions().scales.y,
          title: { display: true, text: 'Chênh lệch (Triệu VND)', color: '#94a3b8' },
        },
        y1: {
          position: 'right',
          grid: { drawOnChartArea: false },
          title: { display: true, text: 'Tỷ lệ chênh lệch (%)', color: '#a855f7' },
          ticks: { color: '#a855f7', callback: (v) => v + '%' },
        },
      },
    },
  };
}

function createSpreadConfig(labels, rows) {
  return {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Spread Mua - Bán (Triệu VND)',
          data: rows.map((r) => (r.sp ? r.sp / 1000000 : null)),
          backgroundColor: 'rgba(244, 63, 94, 0.65)',
          borderRadius: 3,
          yAxisID: 'y',
        },
        {
          type: 'line',
          label: 'Giá Bán SJC (Triệu VND)',
          data: rows.map((r) => (r.s ? r.s / 1000000 : null)),
          borderColor: '#f59e0b',
          borderWidth: 1.8,
          pointRadius: 0,
          spanGaps: true,
          yAxisID: 'y1',
        },
      ],
    },
    options: {
      ...getBaseChartOptions('Spread (Triệu VND)'),
      scales: {
        ...getBaseChartOptions().scales,
        y: {
          ...getBaseChartOptions().scales.y,
          title: { display: true, text: 'Spread (Triệu VND)', color: '#f43f5e' },
        },
        y1: {
          position: 'right',
          grid: { drawOnChartArea: false },
          title: { display: true, text: 'Giá SJC Bán (Triệu VND)', color: '#f59e0b' },
          ticks: { color: '#f59e0b' },
        },
      },
    },
  };
}

function createMacroConfig(labels, rows) {
  return {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'SJC Bán Ra (Triệu VND)',
          data: rows.map((r) => (r.s ? r.s / 1000000 : null)),
          borderColor: '#f59e0b',
          borderWidth: 2,
          pointRadius: 0,
          spanGaps: true,
          yAxisID: 'y',
        },
        {
          label: 'Hợp Đồng GC=F (USD/oz)',
          data: rows.map((r) => r.gu),
          borderColor: '#06b6d4',
          borderWidth: 1.8,
          pointRadius: 0,
          spanGaps: true,
          yAxisID: 'y1',
        },
        {
          label: 'Tỷ Giá USD/VND',
          data: rows.map((r) => r.fx),
          borderColor: '#10b981',
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0,
          spanGaps: true,
          yAxisID: 'y2',
        },
      ],
    },
    options: {
      ...getBaseChartOptions('Triệu VND'),
      scales: {
        ...getBaseChartOptions().scales,
        y: {
          title: { display: true, text: 'Giá SJC (Triệu VND)', color: '#f59e0b' },
          ticks: { color: '#f59e0b' },
        },
        y1: {
          position: 'right',
          grid: { drawOnChartArea: false },
          title: { display: true, text: 'Vàng Thế Giới (USD/oz)', color: '#06b6d4' },
          ticks: { color: '#06b6d4' },
        },
        y2: {
          position: 'right',
          grid: { drawOnChartArea: false },
          title: { display: false },
          ticks: { display: false },
        },
      },
    },
  };
}

function getBaseChartOptions(yTitle = 'Giá trị') {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: 'index',
      intersect: false,
    },
    plugins: {
      legend: {
        display: true,
        position: 'top',
        labels: {
          color: '#cbd5e1',
          font: { family: 'Inter', size: 12 },
          usePointStyle: true,
          boxWidth: 8,
        },
      },
      tooltip: {
        backgroundColor: 'rgba(15, 23, 42, 0.95)',
        titleColor: '#f59e0b',
        bodyColor: '#f8fafc',
        borderColor: 'rgba(245, 158, 11, 0.3)',
        borderWidth: 1,
        padding: 12,
        boxPadding: 6,
        usePointStyle: true,
        bodyFont: { family: 'JetBrains Mono', size: 12 },
        callbacks: {
          label: function (context) {
            let label = context.dataset.label || '';
            if (label) label += ': ';
            if (context.parsed.y !== null) {
              if (label.includes('%')) {
                label += context.parsed.y.toFixed(2) + '%';
              } else if (label.includes('USD/oz')) {
                label += fmtUSD(context.parsed.y);
              } else if (label.includes('USD/VND')) {
                label += fmtCurrency(context.parsed.y);
              } else {
                label += context.parsed.y.toFixed(2) + ' tr ₫';
              }
            }
            return label;
          },
        },
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(255, 255, 255, 0.04)' },
        ticks: { color: '#64748b', maxTicksLimit: 12, font: { family: 'JetBrains Mono', size: 11 } },
      },
      y: {
        grid: { color: 'rgba(255, 255, 255, 0.05)' },
        ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 11 } },
        title: { display: !!yTitle, text: yTitle, color: '#94a3b8' },
      },
    },
  };
}

/* Statistics & Metrics Panel */
function updateStatisticsPanel() {
  const timeline = state.data.timeline;
  if (!timeline || timeline.length === 0) return;

  const validPremiums = timeline.map((r) => r.p).filter((p) => p !== null && !isNaN(p));
  const validSpreads = timeline.map((r) => r.sp).filter((sp) => sp !== null && !isNaN(sp));

  const avgPremium = validPremiums.reduce((a, b) => a + b, 0) / (validPremiums.length || 1);
  const avgSpread = validSpreads.reduce((a, b) => a + b, 0) / (validSpreads.length || 1);

  document.getElementById('statTotalDays').textContent = timeline.length.toLocaleString() + ' ngày';
  document.getElementById('statAthPremium').textContent = fmtMillions(state.data.summary.ath_premium);
  document.getElementById('statAthDate').textContent = state.data.summary.ath_premium_date || '—';
  document.getElementById('statAvgPremium').textContent = fmtMillions(avgPremium);
  document.getElementById('statAvgSpread').textContent = fmtMillions(avgSpread);
}

/* Event Stream */
function renderEventList() {
  const listEl = document.getElementById('eventListStream');
  if (!listEl) return;
  listEl.innerHTML = '';

  const allEvents = state.data.events || [];
  const minDate = state.filteredTimeline.length > 0 ? state.filteredTimeline[0].d : '2011-01-01';
  const maxDate = state.filteredTimeline.length > 0 ? state.filteredTimeline[state.filteredTimeline.length - 1].d : '2026-12-31';

  // Filter events within active range (allEvents is already sorted newest first: 2026 -> 2011)
  let matchedEvents = allEvents.filter((ev) => ev.date >= minDate && ev.date <= maxDate);
  // If window is narrow or has few events, show latest 25 events
  if (matchedEvents.length < 5) {
    matchedEvents = allEvents.slice(0, 30);
  } else {
    matchedEvents = matchedEvents.slice(0, 50);
  }

  const tagLabels = {
    policy: '🏛️ Chính Sách NHNN',
    price_move: '📈 Biến Động SJC',
    fx: '💵 Tỷ Giá USD/VND',
    global: '🌐 Vĩ Mô & Fed',
    cultural: '🧧 Thần Tài & Lễ Tết',
    other: '📌 Tin Thị Trường',
  };

  matchedEvents.forEach((ev) => {
    const catClass = Object.prototype.hasOwnProperty.call(tagLabels, ev.category) ? ev.category : 'other';
    // Tin RSS chỉ được phân loại theo tiêu đề; nhãn này tránh hiểu nhầm
    // chúng là thông báo hoặc quyết định chính thức của NHNN.
    const tagLabel = ev.is_proxy ? '📰 Tin báo chí (sự kiện suy diễn)' : tagLabels[catClass];

    const card = document.createElement('div');
    card.className = `event-card ${catClass}`;
    const meta = document.createElement('div');
    meta.className = 'event-meta';
    const eventDate = document.createElement('span');
    eventDate.className = 'event-date';
    eventDate.textContent = String(ev.date || '');
    const tag = document.createElement('span');
    tag.className = 'event-tag';
    tag.textContent = tagLabel;
    meta.append(eventDate, tag);
    const description = document.createElement('div');
    description.className = 'event-desc';
    // Tiêu đề từ RSS là nội dung bên ngoài, nên đưa vào textContent để
    // không thực thi HTML lạ khi mở bảng sự kiện.
    description.textContent = String(ev.title || '');
    card.append(meta, description);
    if (ev.source_url) {
      try {
        const source = new URL(ev.source_url);
        if (source.protocol === 'https:') {
          const link = document.createElement('a');
          link.href = source.href;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.textContent = 'Xem nguồn tin';
          card.appendChild(link);
        }
      } catch (_) {
        // URL sai định dạng thì chỉ bỏ liên kết; nội dung sự kiện vẫn hiển thị.
      }
    }
    listEl.appendChild(card);
  });
}

/* Interactive Data Table */
function renderDataTable() {
  const tbody = document.getElementById('tableBody');
  if (!tbody) return;
  tbody.innerHTML = '';

  let filtered = state.filteredTimeline;
  if (state.searchQuery) {
    filtered = filtered.filter((r) => r.d.includes(state.searchQuery));
  }

  const total = filtered.length;
  const totalPages = Math.ceil(total / state.tablePageSize) || 1;
  state.tablePage = Math.max(1, Math.min(state.tablePage, totalPages));

  const start = (state.tablePage - 1) * state.tablePageSize;
  const pageRows = filtered.slice().reverse().slice(start, start + state.tablePageSize);

  pageRows.forEach((r) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="color: var(--gold-light); font-weight: 600;">${r.d}</td>
      <td>${fmtCurrency(r.s)}</td>
      <td>${fmtCurrency(r.b)}</td>
      <td>${fmtCurrency(r.sp)}</td>
      <td>${fmtUSD(r.gu)}</td>
      <td>${fmtCurrency(r.gv)}</td>
      <td style="color: ${r.p >= 0 ? 'var(--emerald-success)' : 'var(--rose-danger)'}; font-weight: 600;">
        ${fmtCurrency(r.p)}
      </td>
      <td style="color: ${r.pp >= 0 ? 'var(--emerald-success)' : 'var(--rose-danger)'};">
        ${fmtPct(r.pp)}
      </td>
      <td>${r.fx ? new Intl.NumberFormat('vi-VN').format(r.fx) : '—'}</td>
    `;
    tbody.appendChild(tr);
  });

  document.getElementById('tableShowingText').textContent = 
    `Hiển thị ${Math.min(start + 1, total)} - ${Math.min(start + state.tablePageSize, total)} / ${total} bản ghi`;
  document.getElementById('tablePageText').textContent = `Trang ${state.tablePage} / ${totalPages}`;
  document.getElementById('prevPageBtn').disabled = state.tablePage <= 1;
  document.getElementById('nextPageBtn').disabled = state.tablePage >= totalPages;
}

function changePage(delta) {
  state.tablePage += delta;
  renderDataTable();
}

/* CSV Export */
function exportCsv() {
  const rows = state.filteredTimeline;
  if (!rows || rows.length === 0) return;

  const header = ['Ngày', 'SJC Bán (VND)', 'SJC Mua (VND)', 'Spread (VND)', 'Thế Giới (USD/oz)', 'Thế Giới (VND/lượng)', 'Premium (VND)', 'Premium (%)', 'USD/VND'];
  const csvContent = [
    header.join(','),
    ...rows.map((r) => [
      r.d,
      r.s || '',
      r.b || '',
      r.sp || '',
      r.gu || '',
      r.gv || '',
      r.p || '',
      r.pp || '',
      r.fx || '',
    ].join(',')),
  ].join('\n');

  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `sjc_gold_market_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
  showToast('Đã xuất file CSV thành công!', '📥');
}

/* Live Data Refresh Trigger */
function setUpdateBusy(busy) {
  // Khóa nút trong tab này; server cũng chặn chạy trùng từ các tab khác.
  state.updateRunning = busy;
  const btn = document.getElementById('btnRefreshData');
  if (btn) {
    btn.disabled = busy;
    btn.classList.toggle('loading', busy);
    btn.setAttribute('aria-busy', String(busy));
  }
}

function renderUpdateProgress(result) {
  // Phần trăm chỉ đổi khi pipeline báo mốc mới, không giả lập theo thời gian.
  const panel = document.getElementById('updateProgressPanel');
  if (!panel || result.status === 'idle') return;
  const progress = Math.max(0, Math.min(100, Number(result.progress) || 0));
  panel.hidden = false;
  panel.dataset.status = result.status;
  document.getElementById('updateProgressMessage').textContent = result.message;
  document.getElementById('updateProgressPercent').textContent = `${progress}%`;
  document.getElementById('updateProgressFill').style.width = `${progress}%`;
  const track = document.getElementById('updateProgressTrack');
  track.setAttribute('aria-valuenow', String(progress));
  track.setAttribute('aria-valuetext', `${progress}% — ${result.message}`);
  const seconds = Math.max(0, Math.floor(Number(result.elapsed_seconds) || 0));
  document.getElementById('updateProgressElapsed').textContent =
    `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  document.getElementById('updateProgressDetail').textContent = result.status === 'ok'
    ? (result.snapshot_date ? `Snapshot: ${result.snapshot_date} · Dự báo 1, 3 và 5 tháng đã sẵn sàng.` : 'Dữ liệu và dự báo đã sẵn sàng.')
    : result.connection_lost
      ? 'Lượt cập nhật trên máy chủ có thể vẫn đang chạy. Tải lại trang để nối lại tiến trình.'
    : result.status === 'warning'
      ? 'Lượt cập nhật chưa hoàn tất. Bạn có thể thử lại.'
      : 'Tiến độ theo từng bước; huấn luyện mô hình có thể cần vài phút.';
}

async function trackUpdateProgress(result) {
  // Hỏi tuần tự để không tạo nhiều yêu cầu chồng nhau khi mạng hoặc server chậm.
  let failures = 0;
  renderUpdateProgress(result);
  while (result.status === 'running') {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    try {
      const res = await fetch('/api/update/status', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const next = await res.json();
      if (next.status === 'idle') throw new Error('Lượt cập nhật không còn trên máy chủ');
      result = next;
      failures = 0;
      renderUpdateProgress(result);
    } catch (err) {
      // Thử nối lại để một lỗi mạng ngắn không kết thúc việc theo dõi.
      if (++failures < 3) continue;
      throw err;
    }
  }
  if (result.status === 'ok') await loadData();
  if (result.status === 'warning') console.error('Lỗi cập nhật dữ liệu:', result.log);
  showToast(result.message, result.status === 'ok' ? '✅' : '⚠️');
}

async function restoreUpdateProgress() {
  // Tải lại trang chỉ nối vào lượt đang chạy, không gửi thêm yêu cầu cập nhật.
  try {
    const res = await fetch('/api/update/status', { cache: 'no-store' });
    if (!res.ok) return;
    const result = await res.json();
    if (state.updateRunning) return; // Người dùng vừa bấm cập nhật thì dùng bộ theo dõi đã mở.
    renderUpdateProgress(result);
    // Lượt cập nhật có thể vừa xong sau yêu cầu tải dữ liệu đầu tiên của trang.
    // Nạp lại bản hoàn tất để thanh 100% không nằm trên dashboard còn dữ liệu cũ.
    if (result.status === 'ok') await loadData();
    if (result.status === 'running') {
      setUpdateBusy(true);
      try { await trackUpdateProgress(result); } finally { setUpdateBusy(false); }
    }
  } catch (err) {
    console.error('Không khôi phục được tiến trình cập nhật:', err);
    if (document.getElementById('updateProgressPanel')?.dataset.status === 'running') {
      document.getElementById('updateProgressMessage').textContent = 'Mất kết nối theo dõi. Tải lại trang để kiểm tra tiến trình.';
    }
  }
}

async function handleLiveUpdate() {
  if (state.updateRunning) return;
  setUpdateBusy(true);
  renderUpdateProgress({ status: 'running', progress: 0, message: 'Đang khởi động cập nhật…' });
  showToast('Đang chạy trình thu thập dữ liệu mới...', '🔄');

  try {
    const res = await fetch('/api/update', { method: 'POST' });
    if (res.ok) {
      const result = await res.json();
      await trackUpdateProgress(result);
    } else {
      // HTTP lỗi không có nghĩa dữ liệu mới đã được thu thập thành công.
      const message = `Cập nhật thất bại (HTTP ${res.status}). Snapshot chưa được cập nhật.`;
      renderUpdateProgress({ status: 'warning', progress: 0, message });
      showToast(message, '⚠️');
    }
  } catch (err) {
    console.error('Không kết nối được bộ cập nhật:', err);
    const message = 'Mất kết nối theo dõi. Tải lại trang để kiểm tra tiến trình cập nhật.';
    const progress = Number(document.getElementById('updateProgressTrack')?.getAttribute('aria-valuenow')) || 0;
    renderUpdateProgress({ status: 'warning', progress, message, connection_lost: true });
    showToast(message, '⚠️');
  } finally {
    setUpdateBusy(false);
  }
}

/* Toast System */
function showToast(message, icon = '🔔') {
  let toast = document.getElementById('appToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'appToast';
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  toast.innerHTML = `<span class="toast-icon">${icon}</span><span class="toast-msg">${message}</span>`;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 3500);
}
