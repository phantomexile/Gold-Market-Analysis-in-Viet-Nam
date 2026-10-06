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
      response = await fetch('/api/data');
      if (!response.ok) throw new Error();
    } catch {
      response = await fetch('data/gold_dashboard_data.json');
    }

    if (!response.ok) throw new Error('Không thể tải file dữ liệu');
    state.data = await response.json();
    
    updateKpiCards();
    updateStatisticsPanel();
    renderEventList();
    filterDataByRange();
    renderCurrentChart();
    renderDataTable();
    showToast('Tải thành công 5,558 phiên giao dịch vàng!', '✨');
  } catch (err) {
    console.error('Error loading data:', err);
    showToast('Lỗi nạp dữ liệu: ' + err.message, '❌');
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
    const catClass = ev.category || 'policy';
    const tagLabel = tagLabels[catClass] || ev.type.replace(/_/g, ' ');

    const card = document.createElement('div');
    card.className = `event-card ${catClass}`;
    card.innerHTML = `
      <div class="event-meta">
        <span class="event-date">${ev.date}</span>
        <span class="event-tag">${tagLabel}</span>
      </div>
      <div class="event-desc">${ev.title}</div>
    `;
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
async function handleLiveUpdate() {
  const btn = document.getElementById('btnRefreshData');
  if (btn) btn.classList.add('loading');
  showToast('Đang chạy trình thu thập dữ liệu mới...', '🔄');

  try {
    const res = await fetch('/api/update', { method: 'POST' });
    if (res.ok) {
      const result = await res.json();
      showToast(result.message || 'Cập nhật thành công!', '✅');
      await loadData();
    } else {
      showToast('Đang tải lại dữ liệu cục bộ...', 'ℹ️');
      await loadData();
    }
  } catch (err) {
    showToast('Tải lại dữ liệu cục bộ...', 'ℹ️');
    await loadData();
  } finally {
    if (btn) btn.classList.remove('loading');
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
