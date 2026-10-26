/** Kiểm tra thông báo cuối cùng của nút cập nhật khi API hoặc mạng gặp lỗi. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function check(fetchResult, expected, shouldReload, action = 'handleLiveUpdate()') {
  // Chạy mã thật trong môi trường trình duyệt tối thiểu; không gọi mạng hoặc huấn luyện.
  const messages = [];
  let reloads = 0;
  let loading = false;
  const elements = new Map();
  const context = vm.createContext({
    document: {
      addEventListener() {},
      getElementById: (id) => {
        if (!elements.has(id)) elements.set(id, {
          dataset: {}, style: {}, attributes: {}, hidden: true,
          classList: { toggle: (_, busy) => { loading = busy; } },
          setAttribute(name, value) { this.attributes[name] = value; },
          getAttribute(name) { return this.attributes[name]; },
        });
        return elements.get(id);
      },
    },
    console: { error() {} },
    fetch: fetchResult,
    setTimeout: (callback) => callback(),
    messages,
    reloaded: () => { reloads += 1; },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/js/app.js'), 'utf8'), context);
  vm.runInContext(`
    showToast = (message) => messages.push(message);
    loadData = async () => { reloaded(); showToast('Tải dữ liệu cũ thành công'); };
  `, context);
  await vm.runInContext(action, context);
  assert.match(messages.at(-1), expected);
  assert.equal(reloads, shouldReload ? 1 : 0);
  assert.equal(loading, false, 'Nút phải thoát trạng thái đang cập nhật sau lỗi');
  return elements;
}

(async () => {
  // Thông báo tải dữ liệu không được ghi đè cảnh báo pipeline thất bại.
  await check(async () => ({ ok: true, json: async () => ({
    status: 'warning', message: 'Không thể cập nhật đầy đủ dự báo', log: 'Missing xlrd',
  }) }), /Không thể cập nhật/, false);
  await check(async () => ({ ok: false, status: 404 }), /Snapshot chưa được cập nhật/, false);
  await check(async () => { throw new Error('Disconnected'); }, /Mất kết nối theo dõi/, false);
  await check(async () => ({ ok: true, json: async () => ({
    status: 'ok', message: 'Đã cập nhật dữ liệu và dự báo 1, 3, 5 tháng!',
  }) }), /Đã cập nhật dữ liệu/, true);
  const responses = [
    { status: 'running', progress: 3, message: 'Đang lấy giá', elapsed_seconds: 1 },
    { status: 'running', progress: 68, message: 'Đang huấn luyện dự báo 3 tháng…', elapsed_seconds: 65 },
    { status: 'ok', progress: 100, message: 'Đã cập nhật', snapshot_date: '2026-10-24', elapsed_seconds: 90 },
  ];
  let calls = 0;
  const elements = await check(async () => ({ ok: true, json: async () => responses[calls++] }), /Đã cập nhật/, true);
  assert.equal(calls, 3, 'Phải hỏi trạng thái cho đến khi tiến trình kết thúc');
  assert.equal(elements.get('updateProgressFill').style.width, '100%');
  assert.match(elements.get('updateProgressDetail').textContent, /2026-10-24/);
  assert.equal(elements.get('updateProgressElapsed').textContent, '01:30');

  // Tải lại trang phải chỉ đọc trạng thái, không được khởi động thêm pipeline.
  const restored = [responses[1], responses[2]];
  await check(async (url) => {
    assert.equal(url, '/api/update/status');
    return { ok: true, json: async () => restored.shift() };
  }, /Đã cập nhật/, true, 'restoreUpdateProgress()');
  // Nếu lượt cập nhật vừa xong giữa hai yêu cầu khởi tạo trang, phải nạp lại
  // dashboard thay vì đặt thanh 100% phía trên dữ liệu được đọc trước khi xong.
  await check(async () => ({ ok: true, json: async () => responses[2] }), /Tải dữ liệu cũ thành công/, true, 'restoreUpdateProgress()');
  console.log('7 tình huống cập nhật và khôi phục tiến trình trên web đều đạt.');
})().catch((error) => { console.error(error); process.exitCode = 1; });
