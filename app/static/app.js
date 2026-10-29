const state = {
  overview: null,
  bookings: [],
  rooms: [],
  classrooms: [],
  users: [],
  account: null,
  credit: null,
  complaints: [],
  violations: [],
  analytics: null,
  activeView: "overview",
  session: JSON.parse(localStorage.getItem("studySession") || "null"),
  modal: false,
};
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>'"]/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
        char
      ],
  );
const icon = (name) => `<i data-lucide="${name}"></i>`;
const api = async (url, options = {}) => {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "请求失败");
  return data;
};
const toast = (message) => {
  const node = $("#toast");
  if (!node) return;
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => node.classList.remove("show"), 2400);
};
const status = (label, color) =>
  `<span class="status ${color}">${escapeHtml(label)}</span>`;
const complaintStatus = (value) =>
  value === "已完成"
    ? status(value, "green")
    : value === "处理中"
      ? status(value, "orange")
      : status(value || "待处理", "blue");
const userAvatar = (user, index = 0) =>
  `<div class="tiny-avatar ${["", "pink", "green", "yellow"][index % 4]}">${escapeHtml((user.name || "用").slice(0, 1))}</div>`;
const bookingTiming = (booking) => {
  const notes = [];
  if (Number(booking.late_minutes) > 0)
    notes.push(`迟到 ${Number(booking.late_minutes)} 分钟`);
  if (Number(booking.early_minutes) > 0)
    notes.push(`提前 ${Number(booking.early_minutes)} 分钟签退`);
  return notes.length
    ? `<span class="booking-timing">${notes.join(" · ")}</span>`
    : "";
};
const pageHeader = (title, description, action = "") =>
  `<div class="page-heading"><div><h1>${title}</h1><p>${description}</p></div>${action ? `<div class="heading-actions">${action}</div>` : ""}</div>`;
const actionButton = (label, action, iconName = "plus") =>
  `<button class="primary-btn" data-action="${action}">${icon(iconName)}${label}</button>`;

function renderLogin() {
  document.body.className = "login-mode";
  $("#root").innerHTML =
    `<div class="auth-page"><section class="auth-copy"><div class="auth-brand"><div class="auth-mark">拾</div><span>拾光自习室</span></div><div><h1>让每一次学习，<br>都有一个好位置。</h1><p>自习室预约与运营管理平台，让座位管理、预约服务和学习体验更简单。</p><div class="auth-feature-list"><span>${icon("check-circle-2")}实时座位状态</span><span>${icon("check-circle-2")}灵活预约与签到</span><span>${icon("check-circle-2")}数据驱动运营</span></div></div><div class="auth-foot">© 2026 拾光自习室 · Smart Study Room</div></section><section class="auth-panel"><form class="auth-card" id="login-form"><h2>欢迎回来</h2><p class="subtle">登录你的账户，开始使用自习室服务</p><div class="auth-tabs"><button type="button" class="auth-tab active" data-role="student">学生登录</button><button type="button" class="auth-tab" data-role="admin">管理员登录</button></div><input type="hidden" name="role" value="student"><div class="auth-field"><label id="account-label">学号</label><input name="account" placeholder="请输入学号" autocomplete="username" required></div><div class="auth-field"><label>密码</label><input name="password" type="password" placeholder="请输入密码" autocomplete="current-password" required></div><div class="login-error" id="login-error"></div><button class="primary-btn auth-submit" type="submit">${icon("log-in")}登录</button><p class="login-hint">学生默认密码：123456aa<br>管理员演示账号：admin / admin123456</p></form></section></div>`;
  lucide.createIcons();
}
function renderShell() {
  document.body.className = "";
  $("#root").innerHTML =
    `<div class="app-shell"><aside class="sidebar"><div class="brand"><div class="brand-mark">拾</div><div><strong>拾光自习室</strong><span>ROOM OPERATIONS</span></div></div><div class="workspace-label">工作空间</div><nav class="main-nav">${state.session.role === "admin" ? `<button class="nav-item active" data-view="overview">${icon("layout-dashboard")}<span>运营总览</span></button><button class="nav-item" data-view="bookings">${icon("calendar-check-2")}<span>预约管理</span><b id="booking-badge">0</b></button><button class="nav-item" data-view="seats">${icon("armchair")}<span>座位资源</span></button><button class="nav-item" data-view="classrooms">${icon("building-2")}<span>教室管理</span></button><button class="nav-item" data-view="users">${icon("users")}<span>学生管理</span></button><button class="nav-item" data-view="complaints">${icon("message-square-more")}<span>投诉与反馈</span><b id="complaint-badge">0</b></button><button class="nav-item" data-view="violations">${icon("shield-alert")}<span>违规记录</span></button>` : `<button class="nav-item active" data-view="student-home">${icon("home")}<span>我的预约</span></button><button class="nav-item" data-view="student-feedback">${icon("message-square-plus")}<span>投诉建议</span></button><button class="nav-item" data-view="student-credit">${icon("badge-check")}<span>履约信用</span></button><button class="nav-item" data-view="user-center">${icon("circle-user-round")}<span>用户中心</span></button><button class="nav-item" data-view="student-password">${icon("key-round")}<span>修改密码</span></button>`}</nav><div class="sidebar-bottom"><button class="help-link logout-button" type="button" data-action="logout" aria-label="退出当前账号">${icon("log-out")}<span>退出登录</span>${icon("chevron-right")}</button><button class="profile-mini" type="button" data-view-link="user-center" title="打开用户中心" aria-label="打开用户中心"><div class="avatar avatar-orange">${escapeHtml(state.session.name.slice(0, 1))}</div><div><strong>${escapeHtml(state.session.name)}</strong><span>${state.session.role === "admin" ? "超级管理员" : "学生用户"}</span></div>${icon("more-horizontal")}</button></div></aside><main class="main-content"><header class="topbar"><div class="breadcrumb"><span>${state.session.role === "admin" ? "管理工作台" : "学生服务中心"}</span>${icon("chevron-right")}<strong id="page-title">运营总览</strong></div><div class="top-actions"><span class="live-status"><em></em>数据实时同步</span><span class="sync-time" id="sync-time">刚刚更新</span><button class="icon-btn" title="通知">${icon("bell")}<b></b></button><button class="profile-button" type="button" data-view-link="user-center" title="打开用户中心" aria-label="打开用户中心"><div class="avatar avatar-purple">${escapeHtml(state.session.name.slice(0, 1))}</div><span>${escapeHtml(state.session.name)}</span></button></div></header><div class="page-container" id="app-content"></div></main></div>`;
  lucide.createIcons();
}
async function refresh(shouldRender = true) {
  if (!state.session) return;
  const common = [
    api("/api/bookings"),
    api("/api/rooms"),
    api("/api/classrooms"),
    api("/api/users"),
    api("/api/complaints"),
    api("/api/violations"),
  ];
  const canAutoRender = () =>
    !state.modal &&
    !document.activeElement?.closest?.("#feedback-form") &&
    !document.querySelector('#feedback-form[data-dirty="true"]');
  if (state.session.role === "admin") {
    [
      state.overview,
      state.bookings,
      state.rooms,
      state.classrooms,
      state.users,
      state.complaints,
      state.violations,
      state.analytics,
    ] = await Promise.all([
      api("/api/overview"),
      ...common,
      api("/api/analytics"),
    ]);
    if (shouldRender && canAutoRender()) renderView();
    updateBadges();
  } else {
    [
      state.bookings,
      state.rooms,
      state.account,
      state.credit,
      state.complaints,
    ] = await Promise.all([
      api(`/api/bookings?user_id=${state.session.id}`),
      api("/api/rooms"),
      api(`/api/users/${state.session.id}/account-status`),
      api(`/api/users/${state.session.id}/credit-profile`),
      api(`/api/complaints?user_id=${state.session.id}`),
    ]);
    if (shouldRender && canAutoRender()) renderView();
  }
  if ($("#sync-time")) $("#sync-time").textContent = "刚刚更新";
}
function updateBadges() {
  if ($("#booking-badge"))
    $("#booking-badge").textContent = state.overview.booked;
  if ($("#complaint-badge"))
    $("#complaint-badge").textContent = state.overview.pending_complaints;
}
function setSession(session) {
  state.session = session;
  state.account = null;
  state.credit = null;
  state.complaints = [];
  localStorage.setItem("studySession", JSON.stringify(session));
  state.activeView = session.role === "admin" ? "overview" : "student-home";
  renderShell();
  refresh();
}
function renderView() {
  const renderers = {
    overview: renderOverview,
    bookings: renderBookings,
    seats: renderSeats,
    classrooms: renderClassrooms,
    users: renderUsers,
    complaints: renderComplaints,
    violations: renderViolations,
    "student-home": renderStudentHome,
    "student-feedback": renderStudentFeedback,
    "student-credit": renderStudentCredit,
    "student-password": renderStudentPassword,
    "user-center": renderUserCenter,
  };
  const studentViews = new Set([
    "student-home",
    "student-feedback",
    "student-credit",
    "student-password",
    "user-center",
  ]);
  const view =
    state.session.role === "admin"
      ? renderers[state.activeView]
        ? state.activeView
        : "overview"
      : studentViews.has(state.activeView)
        ? state.activeView
        : "student-home";
  $("#page-title").textContent = {
    overview: "运营总览",
    bookings: "预约管理",
    seats: "座位资源",
    classrooms: "教室管理",
    users: "学生管理",
    complaints: "投诉与反馈",
    violations: "违规记录",
    "student-home": "我的预约",
    "student-feedback": "投诉建议",
    "student-credit": "履约信用",
    "student-password": "修改密码",
    "user-center": "用户中心",
  }[view];
  $("#app-content").innerHTML = renderers[view]();
  document
    .querySelectorAll(".nav-item")
    .forEach((item) =>
      item.classList.toggle("active", item.dataset.view === view),
    );
  lucide.createIcons();
}
const smoothChartPath = (points) =>
  points.reduce((path, point, index) => {
    if (index === 0) return `M ${point.x} ${point.y}`;
    const previous = points[index - 1];
    const controlX = (previous.x + point.x) / 2;
    return `${path} C ${controlX} ${previous.y}, ${controlX} ${point.y}, ${point.x} ${point.y}`;
  }, "");
function renderOverview() {
  const o = state.overview;
  const line = state.analytics.daily;
  const max = Math.max(...line.map((item) => item.value), 1);
  const total = line.reduce((sum, item) => sum + Number(item.value || 0), 0);
  const peak = line.reduce(
    (best, item) => (Number(item.value) > Number(best.value) ? item : best),
    line[0] || { label: "—", value: 0 },
  );
  const chartPoints = line.map((item, index) => ({
    ...item,
    x: 5 + (index / Math.max(line.length - 1, 1)) * 90,
    y: 82 - (Number(item.value || 0) / max) * 62,
  }));
  const linePath = smoothChartPath(chartPoints);
  const areaPath = `${linePath} L 95 92 L 5 92 Z`;
  const zones = state.analytics.zones;
  const maxZone = Math.max(...zones.map((item) => item.value), 1);
  return `${pageHeader("运营总览", "欢迎回来，林管理员。这里是自习室今天的运营情况。", `<span class="sync-time">${icon("refresh-cw")} 每 10 秒自动刷新</span>`)}<div class="stat-grid"><div class="stat-card"><div class="stat-top">今日预约量 <span class="stat-icon icon-orange">${icon("calendar-check-2")}</span></div><div class="stat-number">${o.booked + 18}</div><div class="stat-foot">较昨日 <span class="trend">↗ 12.5%</span></div></div><div class="stat-card"><div class="stat-top">当前使用中 <span class="stat-icon icon-purple">${icon("armchair")}</span></div><div class="stat-number">${o.occupied}<small> / ${o.room_total}</small></div><div class="stat-foot">实时使用率 <span class="trend">${Math.round((o.occupied / o.room_total) * 100)}%</span></div></div><div class="stat-card"><div class="stat-top">活跃学生 <span class="stat-icon icon-green">${icon("users")}</span></div><div class="stat-number">${o.active_users}</div><div class="stat-foot">本周新增 <span class="trend">↗ 8.2%</span></div></div><div class="stat-card"><div class="stat-top">待处理事项 <span class="stat-icon icon-blue">${icon("inbox")}</span></div><div class="stat-number">${o.pending_complaints + o.violation_count}</div><div class="stat-foot">投诉 ${o.pending_complaints} · 违约 ${o.violation_count}</div></div></div><div class="section-grid"><div class="panel"><div class="panel-head"><div><h2>预约趋势</h2><p>近 7 天预约数量变化</p></div><select class="filter-select"><option>近 7 天</option><option>近 30 天</option></select></div><div class="trend-chart"><div class="trend-plot-area"><svg class="trend-svg" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="近 7 天预约趋势"><defs><linearGradient id="chartFade" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#f26e3f" stop-opacity=".24"/><stop offset=".72" stop-color="#f26e3f" stop-opacity=".06"/><stop offset="1" stop-color="#f26e3f" stop-opacity="0"/></linearGradient><filter id="lineGlow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="1.2" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>${[18, 34, 50, 66, 82].map((y) => `<line class="chart-grid" x1="4" y1="${y}" x2="96" y2="${y}"/>`).join("")}<path class="chart-area" d="${areaPath}" vector-effect="non-scaling-stroke"/><path class="chart-line" d="${linePath}" vector-effect="non-scaling-stroke"/></svg><div class="trend-point-layer">${chartPoints.map((point) => `<div class="trend-point ${Number(point.value) === Number(peak.value) && Number(point.value) > 0 ? "is-peak" : ""}" style="left:${point.x}%;top:${point.y}%"><span class="trend-point-value">${point.value}</span><i title="${escapeHtml(point.label)}：${point.value} 次预约"></i></div>`).join("")}</div></div><div class="trend-x-axis">${line.map((item) => `<span>${escapeHtml(item.label)}</span>`).join("")}</div><div class="trend-chart-footer"><span class="trend-legend"><i></i>预约量</span><span>过去 7 天共 <strong>${total}</strong> 次</span><span>峰值 ${escapeHtml(peak.label)} · <strong>${peak.value}</strong> 次</span></div></div></div><div class="panel"><div class="panel-head"><div><h2>区域使用分布</h2><p>各楼层座位占用情况</p></div><button class="panel-link" data-view-link="seats">查看座位 ${icon("arrow-up-right")}</button></div><div class="bar-chart">${zones.map((item, index) => `<div class="bar-column"><div class="bar ${index === 0 ? "active" : ""}" style="height:${Math.max((item.value / maxZone) * 78, 16)}%" title="${item.value} 个座位"></div><label>${item.zone} 区</label></div>`).join("")}</div><div class="legend"><span><i></i>当前使用</span><span><i class="muted"></i>可用座位</span></div><div class="popular-seats-block"><div class="popular-seats-head"><div><strong>最受欢迎座位</strong><span>按有效预约次数统计</span></div><em>爽约率 ${Number(state.analytics.no_show_rate || 0).toFixed(1)}%</em></div>${
    (state.analytics.popular_seats || [])
      .slice(0, 3)
      .map(
        (seat, index) =>
          `<div class="popular-seat-row"><b>${index + 1}</b><div><strong>${escapeHtml(seat.name)}</strong><span>${escapeHtml(seat.classroom_name || "")}</span></div><em>${seat.booking_count} 次</em><small>${seat.violation_count ? `违约 ${seat.violation_count}` : "履约良好"}</small></div>`,
      )
      .join("") || `<div class="empty compact">暂无预约数据</div>`
  }</div></div></div><div class="section-grid"><div class="panel table-panel"><div class="panel-head"><div><h2>最新预约</h2><p>实时预约动态</p></div><button class="panel-link" data-view-link="bookings">查看全部 ${icon("arrow-up-right")}</button></div><table><thead><tr><th>用户</th><th>座位</th><th>预约时段</th><th>状态</th><th>操作</th></tr></thead><tbody>${state.bookings
    .slice(0, 4)
    .map(
      (booking, index) =>
        `<tr><td><div class="user-cell">${userAvatar(booking, index)}${escapeHtml(booking.user_name)}</div></td><td>${escapeHtml(booking.room_name)}</td><td>${booking.start_at.slice(11)} - ${booking.end_at.slice(11)}</td><td>${booking.status === "checked_in" ? status("使用中", "orange") : booking.status === "booked" ? status("已预约", "blue") : booking.status === "violation" ? status("违约", "red") : status(booking.status_label, "gray")}</td><td><button class="action-link" data-booking-id="${booking.id}" data-status="${booking.status === "booked" ? "checked_in" : "completed"}">${booking.status === "booked" ? "签到" : booking.status === "checked_in" ? "签退" : "详情"}</button></td></tr>`,
    )
    .join(
      "",
    )}</tbody></table></div><div class="panel"><div class="panel-head"><div><h2>运营提醒</h2><p>需要你关注的事项</p></div>${icon("more-horizontal")}</div><div class="notice-list"><div class="notice"><i class="notice-mark"></i><div><strong>${state.overview.pending_complaints} 条投诉待处理</strong><p>用户反馈需要及时回复</p></div><time>现在</time></div><div class="notice"><i class="notice-mark red"></i><div><strong>${state.overview.violation_count} 条违约记录</strong><p>请核查用户使用情况</p></div><time>今日</time></div><div class="notice"><i class="notice-mark blue"></i><div><strong>${state.overview.maintenance_rooms} 个座位维修中</strong><p>请在座位资源中跟踪报修和恢复状态</p></div><time>实时</time></div></div></div></div>`;
}
function renderBookings() {
  return `${pageHeader("预约管理", "查看、创建并处理所有座位预约。", actionButton("新建预约", "new-booking", "plus"))}<div class="view-panel table-panel"><div class="panel-head"><div><h2>预约记录</h2><p>共 ${state.bookings.length} 条记录</p></div><div class="table-toolbar"><div class="search-box">${icon("search")}<input id="booking-search" placeholder="搜索用户或座位"></div><select id="booking-status" class="filter-select"><option value="all">全部状态</option><option value="booked">已预约</option><option value="checked_in">使用中</option><option value="completed">已完成</option><option value="violation">违约</option></select></div></div><table><thead><tr><th>编号</th><th>用户</th><th>座位</th><th>预约时段</th><th>来源</th><th>状态</th><th>操作</th></tr></thead><tbody id="booking-table-body">${bookingRows(state.bookings)}</tbody></table></div>`;
}
function bookingRows(items) {
  return (
    items
      .map(
        (b, index) =>
          `<tr><td>#${String(b.id).padStart(4, "0")}</td><td><div class="user-cell">${userAvatar(b, index)}${escapeHtml(b.user_name)}<small>${b.student_no}</small></div></td><td><strong>${escapeHtml(b.room_name)}</strong></td><td>${escapeHtml(b.start_at)}<br><span style="color:#aaa">至 ${escapeHtml(b.end_at.slice(11))}</span>${bookingTiming(b)}</td><td>${b.source === "admin" ? status("管理员", "purple") : status("用户端", "gray")}</td><td>${b.status === "booked" ? status("已预约", "blue") : b.status === "checked_in" ? status("使用中", "orange") : b.status === "violation" ? status("违约", "red") : status(b.status_label, "gray")}</td><td>${b.status === "booked" ? `<button class="action-link" data-booking-id="${b.id}" data-status="checked_in">签到</button><button class="action-link" data-booking-id="${b.id}" data-status="cancelled">取消</button>` : b.status === "checked_in" ? `<button class="action-link" data-booking-id="${b.id}" data-status="completed">签退</button>` : "—"}</td></tr>`,
      )
      .join("") || `<tr><td colspan="7" class="empty">暂无预约记录</td></tr>`
  );
}
function renderSeats() {
  const counts = {
    open: state.rooms.filter((room) => room.status === "open").length,
    occupied: state.rooms.filter((room) => room.status === "occupied").length,
    maintenance: state.rooms.filter((room) => room.status === "maintenance")
      .length,
  };
  return `${pageHeader("座位资源", "座位数量以这里列出的实体座位为唯一数据源。维修中的座位不可预约。", `<button class="ghost-btn" data-action="refresh">${icon("refresh-cw")}刷新状态</button>`)}<div class="seat-summary-grid"><div class="seat-summary-card"><span>${icon("armchair")}座位总数</span><strong>${state.rooms.length}</strong><small>实体座位，不含虚设容量</small></div><div class="seat-summary-card is-open"><span>${icon("circle-check")}可预约</span><strong>${counts.open}</strong><small>当前可创建预约</small></div><div class="seat-summary-card is-occupied"><span>${icon("timer")}使用中</span><strong>${counts.occupied}</strong><small>已签到使用</small></div><div class="seat-summary-card is-maintenance"><span>${icon("wrench")}维修中</span><strong>${counts.maintenance}</strong><small>暂停开放</small></div></div><div class="view-panel"><div class="panel-head"><div><h2>座位地图</h2><p>共 ${state.rooms.length} 个座位 · ${counts.open} 个可预约 · ${counts.maintenance} 个维修中</p></div><div class="table-toolbar seat-filter-toolbar"><div class="search-box">${icon("search")}<input id="seat-search" placeholder="搜索座位或区域"></div><select id="seat-status" class="filter-select"><option value="all">全部状态</option><option value="open">可预约</option><option value="occupied">使用中</option><option value="maintenance">维修中</option></select></div></div><div class="room-grid">${state.rooms.map((room) => `<div class="room-card ${room.status}" data-room-id="${room.id}"><div class="room-card-top"><div><div class="room-name">${escapeHtml(room.name)}</div><div class="room-floor">${escapeHtml(room.classroom_name || room.floor)} · ${room.capacity} 人</div></div>${room.status === "open" ? status("可预约", "green") : room.status === "occupied" ? status("使用中", "orange") : status("维修中", "red")}</div><div class="room-status ${room.status}">${room.status === "open" ? "● 正常开放" : room.status === "occupied" ? "● 当前有人使用" : "● 暂停使用"}</div><div class="room-features">${escapeHtml(room.features || "暂无设施说明")}</div>${room.status_note ? `<div class="room-status-note">${icon(room.status === "maintenance" ? "wrench" : "info")}<span>${escapeHtml(room.status_note)}${room.status_updated_at ? ` · ${escapeHtml(room.status_updated_at)}` : ""}</span></div>` : ""}<div class="room-manage-actions">${room.status === "open" ? `<button class="action-link" type="button" data-action="room-maintenance" data-room-id="${room.id}">${icon("wrench")}报修并停用</button>` : room.status === "maintenance" ? `<button class="action-link room-restore-link" type="button" data-action="room-restore" data-room-id="${room.id}">${icon("circle-check")}恢复可用</button>` : `<span class="room-manage-hint">${icon("lock")}完成签退后可操作</span>`}<button class="action-link" type="button" data-action="seat-history" data-room-id="${room.id}">${icon("history")}预约记录</button></div></div>`).join("")}</div></div>`;
}
function filterSeatCards() {
  const query = ($("#seat-search")?.value || "").trim().toLowerCase();
  const status = $("#seat-status")?.value || "all";
  document.querySelectorAll(".room-card[data-room-id]").forEach((card) => {
    const room = state.rooms.find(
      (item) => item.id === Number(card.dataset.roomId),
    );
    if (!room) return;
    const matchesQuery =
      `${room.name}${room.classroom_name || ""}${room.floor}${room.features}`
        .toLowerCase()
        .includes(query);
    const matchesStatus = status === "all" || room.status === status;
    card.style.display = matchesQuery && matchesStatus ? "" : "none";
  });
}
function seatHistory(roomId) {
  const room = state.rooms.find((item) => item.id === Number(roomId));
  if (!room) return;
  const history = state.bookings
    .filter((item) => item.room_id === Number(roomId))
    .sort((a, b) => b.start_at.localeCompare(a.start_at))
    .slice(0, 12);
  modal(
    `${room.name} · 预约记录`,
    `${room.classroom_name || room.floor} · 共 ${history.length} 条最近记录`,
    `<div class="seat-history-summary"><span>${icon("armchair")}${escapeHtml(room.name)}</span><span>${room.status === "open" ? status("可预约", "green") : room.status === "occupied" ? status("使用中", "orange") : status("维修中", "red")}</span></div><div class="table-panel seat-history-table"><table><thead><tr><th>预约人</th><th>时段</th><th>状态</th><th>异常</th></tr></thead><tbody>${history.map((item) => `<tr><td>${escapeHtml(item.user_name)}<small class="table-subtext">${escapeHtml(item.student_no || "")}</small></td><td>${escapeHtml(item.start_at.slice(5))}<br><span>至 ${escapeHtml(item.end_at.slice(11))}</span></td><td>${item.status === "booked" ? status("已预约", "blue") : item.status === "checked_in" ? status("使用中", "orange") : item.status === "violation" ? status("违约", "red") : status(item.status_label, "gray")}</td><td>${bookingTiming(item) || "正常"}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">该座位暂无预约记录</td></tr>`}</tbody></table></div><div class="modal-actions"><button type="button" class="ghost-btn" data-action="close-modal">关闭</button></div>`,
  );
}
function renderClassrooms() {
  const totalSeats = state.classrooms.reduce(
    (sum, room) => sum + Number(room.seat_count || 0),
    0,
  );
  return `${pageHeader("教室管理", "教室容量由关联座位自动统计，不再手工填写，避免与座位资源数量不一致。", actionButton("新增教室", "new-classroom", "plus"))}<div class="view-panel"><div class="panel-head"><div><h2>教室列表</h2><p>共 ${state.classrooms.length} 间教室 · ${totalSeats} 个实体座位</p></div><div class="table-toolbar"><select id="classroom-status" class="filter-select"><option value="all">全部状态</option><option value="open">开放</option><option value="maintenance">维护中</option></select></div></div><div class="classroom-grid">${state.classrooms.map((room) => `<div class="classroom-card"><div class="room-card-top"><div><div class="room-name">${escapeHtml(room.name)}</div><div class="classroom-meta">${escapeHtml(room.building)} · ${escapeHtml(room.floor)}</div></div>${room.status === "open" ? status("开放", "green") : status("维护中", "red")}</div><div class="classroom-count">${room.seat_count || 0}<small> 个实体座位</small></div><div class="classroom-meta">可用 ${room.available_count || 0} · 使用中 ${room.occupied_count || 0} · 维修 ${room.maintenance_count || 0}</div><div class="classroom-meta">${escapeHtml(room.features || "暂无设施说明")}</div><div class="classroom-actions"><button class="action-link" data-classroom-edit="${room.id}">${icon("pencil")}编辑</button><button class="action-link danger-link" data-classroom-delete="${room.id}">${icon("trash-2")}删除</button></div></div>`).join("")}</div></div>`;
}
function renderUsers() {
  return `${pageHeader("学生管理", "维护学生资料、登录账号、履约信用与黑名单。信用分由预约违约记录自动计算。", `${actionButton("新增学生", "new-student", "plus")}<button class="ghost-btn" data-action="import-csv">${icon("upload")}批量导入</button><button class="ghost-btn" data-action="download-csv">${icon("download")}示例格式</button>`)}<div class="view-panel table-panel"><div class="panel-head"><div><h2>学生档案</h2><p>共 ${state.users.length} 位学生</p></div><div class="table-toolbar"><div class="search-box">${icon("search")}<input id="user-search" placeholder="搜索姓名或学号"></div></div></div><table><thead><tr><th>学生</th><th>联系方式</th><th>履约信用</th><th>违约次数</th><th>账户状态</th><th>操作</th></tr></thead><tbody id="user-table-body">${userRows(state.users)}</tbody></table></div>`;
}
function userRows(items) {
  return (
    items
      .map((user, index) => {
        const score = Number(user.rating || 0);
        const scoreColor =
          score >= 4.5
            ? "var(--green)"
            : score >= 4
              ? "var(--yellow)"
              : "var(--red)";
        return `<tr><td><div class="user-cell">${userAvatar(user, index)}<div>${escapeHtml(user.name)}<small>${user.student_no}</small></div></div></td><td>${escapeHtml(user.phone)}</td><td><strong style="color:${scoreColor}">★ ${score.toFixed(1)}</strong><small class="table-subtext">${escapeHtml(user.credit_level_label || "")}</small></td><td>${user.violations} 次</td><td>${user.blacklisted ? `${status("账号受限", "red")}<small class="table-subtext">${user.unban_date ? `${escapeHtml(user.unban_date)} 解封${user.days_remaining !== null ? ` · 剩余 ${user.days_remaining} 天` : ""}` : "等待管理员设置解封日期"}</small>` : status("正常", "green")}</td><td><button class="action-link" data-action="credit-detail" data-user-id="${user.id}">${icon("badge-check")}信用详情</button><button class="action-link" data-user-edit="${user.id}">${icon("pencil")}编辑</button><button class="action-link danger-link" data-user-delete="${user.id}">${icon("trash-2")}删除</button></td></tr>`;
      })
      .join("") || `<tr><td colspan="6" class="empty">暂无学生</td></tr>`
  );
}
function renderComplaints() {
  return `${pageHeader("投诉与反馈", "集中查看学生提交的投诉、维修请求、建议与账号申诉，并及时记录处理结果。")}<div class="view-panel table-panel"><div class="panel-head"><div><h2>投诉与反馈列表</h2><p>待处理 ${state.overview.pending_complaints} 条</p></div></div><table><thead><tr><th>反馈人</th><th>分类</th><th>主题与座位</th><th>内容</th><th>提交时间</th><th>状态</th><th>操作</th></tr></thead><tbody>${state.complaints.map((item) => `<tr><td><div><strong>${escapeHtml(item.user_name)}</strong><small class="table-subtext">${escapeHtml(item.student_no || "")}</small></div></td><td><span class="feedback-category">${escapeHtml(item.category || "其他")}</span></td><td><strong>${escapeHtml(item.subject)}</strong><small class="table-subtext">${item.room_name ? `关联座位：${escapeHtml(item.room_name)}` : "未关联座位"}</small></td><td class="feedback-table-content">${escapeHtml(item.content)}</td><td>${escapeHtml(item.created_at)}</td><td>${complaintStatus(item.status)}</td><td><button class="action-link" data-complaint-id="${item.id}" data-action="reply-complaint">${item.status === "已完成" ? "查看回复" : "处理反馈"}</button></td></tr>`).join("") || `<tr><td colspan="7" class="empty">暂无投诉或建议</td></tr>`}</tbody></table></div>`;
}
function renderViolations() {
  return `${pageHeader("违规记录", "查看系统自动识别与管理员手动登记的违约行为。", actionButton("手动登记", "manual-violation", "plus"))}<div class="view-panel table-panel"><div class="panel-head"><div><h2>违约记录</h2><p>共 ${state.violations.length} 条记录 · 系统会自动记录未签到行为</p></div></div><table><thead><tr><th>用户</th><th>违约原因</th><th>关联预约</th><th>记录时间</th><th>记录来源</th></tr></thead><tbody>${state.violations.map((item, index) => `<tr><td><div class="user-cell">${userAvatar({ name: item.user_name }, index)}${escapeHtml(item.user_name)}<small>${item.student_no}</small></div></td><td>${escapeHtml(item.reason)}</td><td>${item.booking_id ? `预约 #${String(item.booking_id).padStart(4, "0")}` : "—"}</td><td>${escapeHtml(item.created_at)}</td><td>${item.source === "system" ? status("系统自动", "purple") : status("管理员登记", "orange")}</td></tr>`).join("")}</tbody></table></div>`;
}
function renderStudentHome() {
  const mine = state.bookings.filter(
    (item) => item.user_id === state.session.id,
  );
  const limited = Boolean(state.account?.is_blacklisted);
  const action = limited
    ? `<button class="primary-btn" type="button" disabled>${icon("lock-keyhole")}账号受限，暂不可预约</button>`
    : actionButton("预约座位", "new-booking", "plus");
  const reason = state.account?.blacklist_reason
    ? `<span class="account-alert-reason">限制原因：${escapeHtml(state.account.blacklist_reason)}</span>`
    : "";
  const limitNotice = limited
    ? `<div class="account-alert"><div class="account-alert-icon">${icon("shield-alert")}</div><div><strong>你的账号已被限制使用</strong><p>${escapeHtml(state.account.status_message)}</p>${reason}</div><button class="ghost-btn" type="button" data-view-link="user-center">查看账户通知 ${icon("arrow-right")}</button></div>`
    : "";
  const credit = state.credit
    ? `<button class="home-credit-card" type="button" data-view-link="student-credit"><span>${icon("badge-check")}履约信用</span><strong>${Number(state.credit.score).toFixed(1)}<small> / 5.0</small></strong><em>${escapeHtml(state.credit.level_label)} · 查看评分依据</em></button>`
    : "";
  return `<div class="student-portal">${pageHeader("我的预约", "查看你的学习安排和座位使用状态。", action)}${limitNotice}<div class="home-summary-row">${credit}<div class="home-summary-card"><span>${icon("calendar-check-2")}预约记录</span><strong>${mine.length}</strong><em>当前账号下的全部预约</em></div></div><div class="student-booking-grid">${mine.map((item) => `<div class="student-booking"><div class="room-card-top"><strong>${escapeHtml(item.room_name)}</strong>${item.status === "booked" ? status("已预约", "blue") : item.status === "checked_in" ? status("使用中", "orange") : status(item.status_label, "gray")}</div><p>${escapeHtml(item.start_at)} - ${escapeHtml(item.end_at.slice(11))}</p>${item.status === "booked" ? `<div class="classroom-actions"><button class="action-link" data-booking-id="${item.id}" data-status="cancelled">取消预约</button></div>` : ""}${bookingTiming(item) ? `<div class="student-booking-timing">${bookingTiming(item)}</div>` : ""}</div>`).join("") || '<div class="panel empty">还没有预约，先为自己找一个好位置吧。</div>'}</div></div>`;
}
function renderStudentFeedback() {
  const categories = [
    "服务投诉",
    "设施维修",
    "座位环境",
    "预约服务",
    "账号申诉",
    "服务建议",
    "其他",
  ];
  const history = state.complaints;
  const seatOptions = state.rooms
    .map(
      (room) =>
        `<option value="${room.id}">${escapeHtml(room.name)} · ${escapeHtml(room.classroom_name || room.floor)}</option>`,
    )
    .join("");
  return `<div class="student-portal">${pageHeader("投诉与建议", "投诉、报修、建议或账号申诉都会进入同一处理队列，进度和管理员回复会在这里同步。")}<div class="feedback-layout"><section class="panel feedback-form-panel"><div class="feedback-panel-title"><span class="feedback-title-icon">${icon("message-square-plus")}</span><div><h2>提交投诉或建议</h2><p>可选择关联座位，方便管理员定位具体位置和维修问题。</p></div></div><form id="feedback-form" class="feedback-form"><div class="feedback-two-col"><div class="auth-field"><label>反馈类型</label><select name="category" class="filter-select" required>${categories.map((item) => `<option value="${item}">${item}</option>`).join("")}</select></div><div class="auth-field"><label>关联座位</label><select name="room_id" class="filter-select"><option value="">不关联具体座位</option>${seatOptions}</select></div></div><div class="auth-field"><label>反馈主题</label><input name="subject" maxlength="60" placeholder="用一句话概括问题或建议" required></div><div class="auth-field"><label>详细描述</label><textarea name="content" rows="7" minlength="5" maxlength="1000" placeholder="例如：靠窗座位台灯无法开启，希望安排维修……" required></textarea></div><div class="feedback-tip">${icon("info")}投诉与报修会进入管理员处理队列；账号受限时也可以在这里提交申诉。</div><div class="feedback-submit-row"><span>请勿提交密码等敏感信息</span><button class="primary-btn" type="submit">${icon("send")}提交反馈</button></div></form></section><section class="panel feedback-history"><div class="panel-head"><div><h2>我的记录</h2><p>共 ${history.length} 条记录，按提交时间倒序排列</p></div><span class="feedback-live-badge">${icon("refresh-cw")}自动同步</span></div><div class="feedback-list">${history.map((item) => `<article class="feedback-item"><div class="feedback-item-head"><div><span class="feedback-category">${escapeHtml(item.category || "其他")}</span><strong>${escapeHtml(item.subject)}</strong></div>${complaintStatus(item.status)}</div><p>${escapeHtml(item.content)}</p><div class="feedback-item-foot"><time>${escapeHtml(item.created_at)}</time><span>${item.room_name ? `座位 ${escapeHtml(item.room_name)}` : "未关联座位"} · #${String(item.id).padStart(4, "0")}</span></div>${item.reply ? `<div class="feedback-reply"><span>${icon("message-circle-reply")}管理员回复</span><p>${escapeHtml(item.reply)}</p></div>` : ""}</article>`).join("") || `<div class="feedback-empty">${icon("inbox")}<strong>还没有投诉或建议</strong><p>左侧表单会记录你的每一条反馈和处理结果。</p></div>`}</div></section></div></div>`;
}
function renderUserCenter() {
  if (state.session.role === "admin") {
    return `<div class="student-portal">${pageHeader("用户中心", "查看管理员账号身份与工作台快捷入口。")}<div class="account-layout"><aside class="account-profile-card is-admin"><span class="account-kicker">ROOM ADMINISTRATOR</span><div class="account-avatar">${escapeHtml(state.session.name.slice(0, 1))}</div><h2>${escapeHtml(state.session.name)}</h2><p>${escapeHtml(state.session.account)}</p><div class="account-profile-divider"></div><div class="account-profile-row"><span>账号角色</span><strong>超级管理员</strong></div><div class="account-profile-row"><span>账号状态</span><strong class="account-good-text">正常</strong></div><div class="account-profile-row"><span>数据权限</span><strong>全部工作台</strong></div></aside><div class="account-main"><section class="account-status-card"><div class="account-status-head"><div><span class="account-kicker">ACCOUNT STATUS</span><h2>管理员账号状态正常</h2><p>当前账号可访问全部运营管理功能，不受黑名单限制。</p></div>${status("状态正常", "green")}</div><div class="account-countdown"><span>管理权限</span><strong>全部开放</strong><p>预约、学生、投诉反馈与违约记录均可管理</p></div></section><div class="account-meta-grid"><div class="account-meta-card"><span>${icon("shield-check")}</span><div><small>安全状态</small><strong>正常</strong></div></div><div class="account-meta-card"><span>${icon("message-square-more")}</span><div><small>待处理反馈</small><strong>${state.overview?.pending_complaints ?? 0} 条</strong></div></div><div class="account-meta-card"><span>${icon("users")}</span><div><small>在册学生</small><strong>${state.users.length} 人</strong></div></div><div class="account-meta-card"><span>${icon("armchair")}</span><div><small>实体座位</small><strong>${state.rooms.length} 个</strong></div></div></div><div class="account-service-grid"><button class="account-service-card" type="button" data-view-link="overview">${icon("layout-dashboard")}<strong>返回运营总览</strong><span>查看今日运营数据 ${icon("arrow-right")}</span></button><button class="account-service-card" type="button" data-view-link="complaints">${icon("message-square-more")}<strong>处理投诉反馈</strong><span>查看待处理事项 ${icon("arrow-right")}</span></button><button class="account-service-card" type="button" data-view-link="seats">${icon("wrench")}<strong>座位维修管理</strong><span>报修与恢复座位状态 ${icon("arrow-right")}</span></button></div></div></div></div>`;
  }
  const account = state.account;
  if (!account) {
    return `<div class="student-portal">${pageHeader("用户中心", "正在读取你的账号状态。")}<div class="panel empty">${icon("loader-circle")}正在加载账号信息...</div></div>`;
  }
  const limited = Boolean(account.is_blacklisted);
  const daysValue = limited
    ? account.days_remaining === null
      ? "待确认"
      : account.days_remaining === 0
        ? "今天"
        : `${account.days_remaining}<small> 天</small>`
    : "正常";
  const countdownLabel = limited ? "距离解封" : "预约权限";
  const countdownNote = limited
    ? account.unban_date
      ? `预计 ${escapeHtml(account.unban_date)} 23:59 解封`
      : "管理员尚未设置具体解封日期"
    : "账号未被拉黑，可正常预约座位";
  const blacklistDetail = limited
    ? `<div class="blacklist-notice"><div class="blacklist-notice-icon">${icon("bell-ring")}</div><div><strong>你已收到账号限制通知</strong><p>${escapeHtml(account.blacklist_reason || "请联系管理员了解限制原因")}</p><span>${account.blacklisted_at ? `限制时间：${escapeHtml(account.blacklisted_at)}` : "限制时间未记录"}${account.unban_date ? ` · 预计 ${escapeHtml(account.unban_date)} 解封` : ""}</span></div></div>`
    : "";
  return `<div class="student-portal">${pageHeader("用户中心", "查看个人资料、账号状态、解封倒计时与安全服务。")}<div class="account-layout"><aside class="account-profile-card ${limited ? "is-limited" : ""}"><span class="account-kicker">STUDY ROOM MEMBER</span><div class="account-avatar">${escapeHtml(account.name.slice(0, 1))}</div><h2>${escapeHtml(account.name)}</h2><p>${escapeHtml(account.student_no)}</p><div class="account-profile-divider"></div><div class="account-profile-row"><span>账号角色</span><strong>学生用户</strong></div><div class="account-profile-row"><span>履约信用</span><strong>★ ${Number(account.rating || 0).toFixed(1)} · ${escapeHtml(account.credit_level_label || "")}</strong></div><div class="account-profile-row"><span>违约记录</span><strong>${account.violations} 次</strong></div><button class="account-feedback-btn" type="button" data-view-link="student-feedback">${icon("message-square-plus")}投诉、报修或账号申诉</button></aside><div class="account-main"><section class="account-status-card ${limited ? "is-limited" : ""}"><div class="account-status-head"><div><span class="account-kicker">ACCOUNT STATUS</span><h2>${limited ? "当前账号处于受限状态" : "当前账号状态正常"}</h2><p>${escapeHtml(account.status_message)}</p></div>${status(account.status_label, limited ? "red" : "green")}</div><div class="account-countdown"><span>${countdownLabel}</span><strong>${daysValue}</strong><p>${countdownNote}</p></div></section>${blacklistDetail}<div class="account-meta-grid"><div class="account-meta-card"><span>${icon("id-card")}</span><div><small>学号</small><strong>${escapeHtml(account.student_no)}</strong></div></div><div class="account-meta-card"><span>${icon("phone")}</span><div><small>绑定手机</small><strong>${escapeHtml(account.phone || "未填写")}</strong></div></div><div class="account-meta-card"><span>${icon("badge-check")}</span><div><small>履约信用</small><strong>${Number(account.rating || 0).toFixed(1)} / 5.0</strong></div></div><div class="account-meta-card"><span>${icon("triangle-alert")}</span><div><small>违约次数</small><strong>${account.violations} 次</strong></div></div></div><div class="account-service-grid"><button class="account-service-card" type="button" data-view-link="student-credit">${icon("badge-check")}<strong>履约信用</strong><span>查看自动评分与违约明细 ${icon("arrow-right")}</span></button><button class="account-service-card" type="button" data-view-link="student-feedback">${icon("message-square-plus")}<strong>投诉建议</strong><span>提交投诉、报修或账号申诉 ${icon("arrow-right")}</span></button><button class="account-service-card" type="button" data-view-link="student-password">${icon("key-round")}<strong>账户安全</strong><span>修改当前登录密码 ${icon("arrow-right")}</span></button></div></div></div></div>`;
}
function renderStudentCredit() {
  const credit = state.credit;
  if (!credit) {
    return `<div class="student-portal">${pageHeader("履约信用", "正在计算你的信用记录。")}<div class="panel empty">${icon("loader-circle")}正在加载信用信息...</div></div>`;
  }
  const score = Number(credit.score || 0);
  const levelColor = ["risk", "high_risk"].includes(credit.level)
    ? "red"
    : credit.level === "watch"
      ? "orange"
      : "green";
  const counts = credit.booking_counts || {};
  const violations = credit.recent_violations || [];
  return `<div class="student-portal">${pageHeader("履约信用", "信用分根据可核验的预约履约记录自动计算，不采用学生互评。")}<div class="credit-layout"><section class="credit-score-card ${credit.level}"><span class="account-kicker">FULFILLMENT CREDIT</span><div class="credit-score-heading"><div><h2>${escapeHtml(credit.level_label)}</h2><p>${escapeHtml(credit.rule)}</p></div>${status(credit.level_label, levelColor)}</div><div class="credit-score-value">${score.toFixed(1)}<small> / ${Number(credit.max_score).toFixed(1)}</small></div><div class="credit-progress"><i style="width:${Math.max(4, (score / Number(credit.max_score || 5)) * 100)}%"></i></div><div class="credit-score-foot"><span>已扣 ${Number(credit.score_lost).toFixed(1)} 分</span><span>再记 1 次违约将变为 ${Number(credit.next_violation_score).toFixed(1)} 分</span></div></section><section class="panel credit-rule-panel"><div class="panel-head"><div><h2>为什么不是学生互评？</h2><p>自习室场景更适合评价履约行为</p></div>${icon("info")}</div><div class="credit-rule-list"><div><span>${icon("user-check")}</span><div><strong>不采用学生评价学生</strong><p>同学之间没有稳定的服务关系，互评容易产生主观性和恶意评分。</p></div></div><div><span>${icon("calendar-check-2")}</span><div><strong>根据预约与违约记录计算</strong><p>系统只使用可核验的违约次数、预约完成情况和账号状态。</p></div></div><div><span>${icon("rotate-ccw")}</span><div><strong>${credit.recovery_days} 天自动恢复</strong><p>每条违约记录满 ${credit.recovery_days} 天后不再计入信用分${credit.next_recovery_date ? `，预计下一条于 ${escapeHtml(credit.next_recovery_date)} 恢复` : ""}。</p></div></div></div></section></div><div class="credit-stat-grid"><div class="credit-stat-card"><span>完成预约</span><strong>${counts.completed || 0}</strong><small>正常履约记录</small></div><div class="credit-stat-card"><span>取消预约</span><strong>${counts.cancelled || 0}</strong><small>当前规则不扣分</small></div><div class="credit-stat-card is-risk"><span>信用扣分记录</span><strong>${credit.violation_count || 0}</strong><small>累计 ${credit.total_violation_count || 0} 条 · 超过 ${credit.recovery_days} 天自动恢复</small></div><div class="credit-stat-card"><span>进行中预约</span><strong>${(counts.booked || 0) + (counts.checked_in || 0)}</strong><small>已预约或使用中</small></div></div><div class="panel table-panel credit-history-panel"><div class="panel-head"><div><h2>最近违约记录</h2><p>信用分会随违约登记和管理员调整实时更新</p></div></div><table><thead><tr><th>原因</th><th>关联座位</th><th>来源</th><th>时间</th><th>信用影响</th></tr></thead><tbody>${violations.map((item) => `<tr><td>${escapeHtml(item.reason)}</td><td>${item.room_name ? escapeHtml(item.room_name) : "—"}</td><td>${item.source === "system" ? status("系统判定", "purple") : status("管理员登记", "orange")}</td><td>${escapeHtml(item.created_at)}</td><td>${item.is_active ? `<strong class="credit-negative">−0.4 分</strong>` : status("已恢复", "green")}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">暂无违约记录，继续保持正常预约和签到即可</td></tr>`}</tbody></table></div></div>`;
}
function renderStudentPassword() {
  return `<div class="student-portal">${pageHeader("修改密码", "定期修改密码，保护你的账户安全。")}<div class="panel"><form id="password-form" class="form-row"><div class="auth-field wide"><label>原密码</label><input name="old_password" type="password" required></div><div class="auth-field wide"><label>新密码</label><input name="new_password" type="password" minlength="6" required></div><button class="primary-btn" type="submit">${icon("key-round")}确认修改</button></form></div></div>`;
}
function modal(title, subtitle, body) {
  state.modal = true;
  document.body.insertAdjacentHTML(
    "beforeend",
    `<div class="modal-backdrop" id="modal-backdrop"><div class="modal"><div class="modal-head"><div><h2>${title}</h2><p>${subtitle || ""}</p></div><button class="icon-btn" data-action="close-modal">${icon("x")}</button></div><div class="modal-body">${body}</div></div></div>`,
  );
  lucide.createIcons();
}
function closeModal() {
  $("#modal-backdrop")?.remove();
  state.modal = false;
}
function seatMaintenanceForm(room) {
  if (!room) return;
  modal(
    `报修座位 ${room.name}`,
    "报修后座位会立即进入维修中状态，暂停预约；维修完成后再恢复可用。",
    `<form id="seat-maintenance-form" data-id="${room.id}"><div class="seat-modal-summary"><div>${icon("armchair")}<div><strong>${escapeHtml(room.name)}</strong><span>${escapeHtml(room.classroom_name || room.floor)}</span></div></div>${status("当前可预约", "green")}</div><div class="auth-field"><label>维修原因</label><textarea name="note" rows="4" maxlength="200" placeholder="如：台灯损坏，预计今天下午维修" required></textarea></div><div class="feedback-tip">${icon("info")}如果该座位还有已预约或使用中的记录，系统会阻止报修并提示先处理预约。</div><div class="modal-actions"><button type="button" class="ghost-btn" data-action="close-modal">取消</button><button class="primary-btn" type="submit">${icon("wrench")}确认报修并停用</button></div></form>`,
  );
}
async function creditDetail(userId) {
  try {
    const credit = await api(`/api/users/${userId}/credit-profile`);
    modal(
      `${credit.name} · 履约信用`,
      credit.rule,
      `<div class="credit-detail-head"><div class="credit-detail-score">${Number(credit.score).toFixed(1)}<small> / 5.0</small></div><div><strong>${escapeHtml(credit.level_label)}</strong><p>累计违约 ${credit.violation_count} 次 · 已扣 ${Number(credit.score_lost).toFixed(1)} 分</p></div></div><div class="credit-detail-stats"><span>完成预约 <strong>${credit.booking_counts.completed || 0}</strong></span><span>取消预约 <strong>${credit.booking_counts.cancelled || 0}</strong></span><span>违约记录 <strong>${credit.booking_counts.violation || 0}</strong></span></div><div class="credit-detail-list">${(credit.recent_violations || []).map((item) => `<div><span>${icon("triangle-alert")}</span><div><strong>${escapeHtml(item.reason)}</strong><p>${escapeHtml(item.created_at)}${item.room_name ? ` · 座位 ${escapeHtml(item.room_name)}` : ""}</p></div><em>−0.4</em></div>`).join("") || `<div class="empty">暂无违约记录</div>`}</div><div class="modal-actions"><button type="button" class="ghost-btn" data-action="close-modal">关闭</button></div>`,
    );
  } catch (error) {
    toast(error.message);
  }
}
function classroomForm(item = {}) {
  modal(
    item.id ? "编辑教室" : "新增教室",
    "座位数量和开放状态由座位资源自动统计，不再手工填写。",
    `<form id="classroom-form" data-id="${item.id || ""}"><div class="modal-grid"><div class="auth-field"><label>教室名称</label><input name="name" value="${escapeHtml(item.name || "")}" placeholder="如：一层安静区" required></div><div class="auth-field"><label>楼栋</label><input name="building" value="${escapeHtml(item.building || "主楼")}" required></div><div class="auth-field"><label>楼层</label><input name="floor" value="${escapeHtml(item.floor || "一层")}" required></div><div class="auth-field full"><label>设施属性</label><input name="features" value="${escapeHtml(item.features || "")}" placeholder="白板 · 电源"></div><div class="feedback-tip full">${icon("info")}当前统计到 ${item.seat_count || 0} 个实体座位，全部座位维修时教室会自动显示为维护中。</div></div><div class="modal-actions"><button type="button" class="ghost-btn" data-action="close-modal">取消</button><button class="primary-btn" type="submit">${icon("check")}保存教室</button></div></form>`,
  );
}
function studentForm(item = {}) {
  const untilDate = (item.blacklisted_until || "").slice(0, 10);
  modal(
    item.id ? "编辑学生" : "新增学生",
    "设为受限账号时必须填写原因和解封日期，学生登录后会收到明确的账号通知。",
    `<form id="student-form" data-id="${item.id || ""}"><div class="modal-grid"><div class="auth-field"><label>姓名</label><input name="name" value="${escapeHtml(item.name || "")}" required></div><div class="auth-field"><label>学号</label><input name="student_no" value="${escapeHtml(item.student_no || "")}" required></div><div class="auth-field"><label>手机号</label><input name="phone" value="${escapeHtml(item.phone || "")}"></div><div class="auth-field"><label>登录密码</label><input name="password" value="" placeholder="留空则不修改"></div><div class="auth-field"><label>账户状态</label><select id="student-blacklist-status" name="blacklisted" class="filter-select"><option value="false" ${!item.blacklisted ? "selected" : ""}>正常</option><option value="true" ${item.blacklisted ? "selected" : ""}>账号受限</option></select></div><div class="auth-field"><label>解封日期</label><input id="student-blacklist-until" name="blacklisted_until" type="date" value="${untilDate}" ${!item.blacklisted ? "disabled" : ""}><small class="field-help">留空时默认 7 天后解封</small></div><div class="auth-field full"><label>限制原因</label><input id="student-blacklist-reason" name="blacklist_reason" maxlength="200" value="${escapeHtml(item.blacklist_reason || "")}" placeholder="如：多次预约后未签到" ${!item.blacklisted ? "disabled" : ""}><small class="field-help">该原因会显示在学生的用户中心和登录后的提醒中。</small></div></div><div class="modal-actions"><button type="button" class="ghost-btn" data-action="close-modal">取消</button><button class="primary-btn" type="submit">${icon("check")}保存学生</button></div></form>`,
  );
}
function bookingForm() {
  const currentUser = state.account
    ? {
        id: state.account.id,
        name: state.account.name,
        student_no: state.account.student_no,
        blacklisted: state.account.is_blacklisted,
      }
    : null;
  const users =
    state.session.role === "student"
      ? [currentUser].filter(Boolean)
      : state.users.filter((item) => !item.blacklisted);
  modal(
    "新建预约",
    "选择座位和使用时段，提交后可在预约管理中跟踪。",
    `<form id="booking-form"><div class="modal-grid"><div class="auth-field"><label>预约人</label><select name="user_id" class="filter-select" required>${users.map((u) => `<option value="${u.id}">${escapeHtml(u.name)} · ${u.student_no}</option>`).join("")}</select></div><div class="auth-field"><label>座位</label><select name="room_id" class="filter-select" required>${state.rooms
      .filter((r) => r.status === "open")
      .map(
        (r) =>
          `<option value="${r.id}">${escapeHtml(r.name)} · ${escapeHtml(r.floor)}</option>`,
      )
      .join(
        "",
      )}</select></div><div class="auth-field"><label>开始时间</label><input name="start_at" type="datetime-local" required></div><div class="auth-field"><label>结束时间</label><input name="end_at" type="datetime-local" required></div></div><div class="modal-actions"><button type="button" class="ghost-btn" data-action="close-modal">取消</button><button class="primary-btn" type="submit">${icon("calendar-check-2")}确认预约</button></div></form>`,
  );
}
function violationForm() {
  modal(
    "登记违约",
    "记录一次人工发现的违规行为。",
    `<form id="violation-form"><div class="modal-grid"><div class="auth-field"><label>学生</label><select name="user_id" class="filter-select" required>${state.users.map((u) => `<option value="${u.id}">${escapeHtml(u.name)} · ${u.student_no}</option>`).join("")}</select></div><div class="auth-field"><label>违约原因</label><input name="reason" placeholder="如：未按规定使用座位" required></div></div><div class="modal-actions"><button type="button" class="ghost-btn" data-action="close-modal">取消</button><button class="primary-btn" type="submit">${icon("shield-alert")}确认登记</button></div></form>`,
  );
}
function complaintForm(id) {
  const item = state.complaints.find((row) => row.id === Number(id));
  modal(
    item.status === "已完成" ? "查看反馈回复" : "处理学生反馈",
    item.subject,
    `<form id="complaint-form" data-id="${item.id}"><div class="feedback-modal-meta"><span>${icon("user-round")}${escapeHtml(item.user_name)}</span><span>${icon("tag")}${escapeHtml(item.category || "其他")}</span><span>${icon("armchair")}${item.room_name ? escapeHtml(item.room_name) : "未关联座位"}</span><span>${icon("clock-3")}${escapeHtml(item.created_at)}</span></div><div class="csv-help feedback-modal-content">${escapeHtml(item.content)}</div><div class="auth-field" style="margin-top:14px"><label>处理状态</label><select name="status" class="filter-select"><option ${item.status === "待处理" ? "selected" : ""}>待处理</option><option ${item.status === "处理中" ? "selected" : ""}>处理中</option><option ${item.status === "已完成" ? "selected" : ""}>已完成</option></select></div><div class="auth-field"><label>回复内容</label><textarea name="reply" rows="4" placeholder="请输入处理结果或给学生的回复">${escapeHtml(item.reply || "")}</textarea></div><div class="modal-actions"><button type="button" class="ghost-btn" data-action="close-modal">关闭</button><button class="primary-btn" type="submit">${icon("send")}保存反馈</button></div></form>`,
  );
}

async function submitJson(url, method, payload, success) {
  try {
    await api(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    closeModal();
    document.activeElement?.blur?.();
    document
      .querySelectorAll('[data-dirty="true"]')
      .forEach((node) => node.removeAttribute("data-dirty"));
    await refresh();
    toast(success);
  } catch (error) {
    toast(error.message);
  }
}
async function handleSubmit(event) {
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  if (form.id === "login-form") {
    try {
      const session = await api("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account: data.account,
          password: data.password,
          role: data.role,
        }),
      });
      setSession(session);
    } catch (error) {
      $("#login-error").textContent = error.message;
    }
    return;
  }
  if (form.id === "classroom-form") {
    const payload = { ...data };
    const itemId = form.dataset.id;
    await submitJson(
      itemId ? `/api/classrooms/${itemId}` : "/api/classrooms",
      itemId ? "PATCH" : "POST",
      payload,
      "教室保存成功",
    );
  }
  if (form.id === "student-form") {
    const payload = {
      ...data,
      blacklisted: data.blacklisted === "true",
      blacklisted_until: data.blacklisted_until || null,
      blacklist_reason: data.blacklist_reason || "",
    };
    if (!payload.password) delete payload.password;
    const itemId = form.dataset.id;
    await submitJson(
      itemId ? `/api/users/${itemId}` : "/api/users",
      itemId ? "PATCH" : "POST",
      payload,
      "学生信息保存成功",
    );
  }
  if (form.id === "booking-form") {
    data.start_at = data.start_at.replace("T", " ");
    data.end_at = data.end_at.replace("T", " ");
    await submitJson(
      "/api/bookings",
      "POST",
      { ...data, user_id: Number(data.user_id), room_id: Number(data.room_id) },
      "预约创建成功",
    );
  }
  if (form.id === "violation-form")
    await submitJson(
      "/api/violations",
      "POST",
      { user_id: Number(data.user_id), reason: data.reason },
      "已登记违约",
    );
  if (form.id === "feedback-form")
    await submitJson(
      "/api/complaints",
      "POST",
      {
        user_id: state.session.id,
        room_id: data.room_id ? Number(data.room_id) : null,
        category: data.category,
        subject: data.subject,
        content: data.content,
      },
      "反馈已提交，管理员会尽快处理",
    );
  if (form.id === "seat-maintenance-form")
    await submitJson(
      `/api/rooms/${form.dataset.id}/status`,
      "PATCH",
      { status: "maintenance", note: data.note },
      "座位已进入维修状态",
    );
  if (form.id === "complaint-form")
    await submitJson(
      `/api/complaints/${form.dataset.id}`,
      "PATCH",
      { status: data.status, reply: data.reply },
      "反馈已更新",
    );
  if (form.id === "password-form")
    await submitJson(
      `/api/users/${state.session.id}/password`,
      "PATCH",
      data,
      "密码修改成功",
    );
}

document.addEventListener("submit", handleSubmit);
document.addEventListener("click", async (event) => {
  const tab = event.target.closest(".auth-tab");
  if (tab) {
    document
      .querySelectorAll(".auth-tab")
      .forEach((item) => item.classList.toggle("active", item === tab));
    $('#login-form [name="role"]').value = tab.dataset.role;
    $("#account-label").textContent =
      tab.dataset.role === "admin" ? "管理员账号" : "学号";
    $('#login-form [name="account"]').placeholder =
      tab.dataset.role === "admin" ? "请输入管理员账号" : "请输入学号";
    return;
  }
  const nav = event.target.closest(".nav-item");
  if (nav) {
    state.activeView = nav.dataset.view;
    renderView();
    return;
  }
  const viewLink = event.target.closest("[data-view-link]");
  if (viewLink) {
    state.activeView = viewLink.dataset.viewLink;
    if (
      state.activeView === "user-center" &&
      state.session.role === "student" &&
      !state.account
    )
      await refresh(false);
    renderView();
    return;
  }
  const action = event.target.closest("[data-action]");
  if (action) {
    const name = action.dataset.action;
    if (name === "logout") {
      localStorage.removeItem("studySession");
      state.session = null;
      state.account = null;
      state.complaints = [];
      closeModal();
      renderLogin();
    }
    if (name === "user-center") {
      state.activeView = "user-center";
      if (state.session.role === "student" && !state.account)
        await refresh(false);
      renderView();
    }
    if (name === "close-modal") closeModal();
    if (name === "new-booking") bookingForm();
    if (name === "new-classroom") classroomForm();
    if (name === "new-student") studentForm();
    if (name === "manual-violation") violationForm();
    if (name === "reply-complaint") complaintForm(action.dataset.complaintId);
    if (name === "credit-detail") await creditDetail(action.dataset.userId);
    if (name === "seat-history") seatHistory(action.dataset.roomId);
    if (name === "room-maintenance")
      seatMaintenanceForm(
        state.rooms.find((room) => room.id === Number(action.dataset.roomId)),
      );
    if (name === "room-restore") {
      const room = state.rooms.find(
        (item) => item.id === Number(action.dataset.roomId),
      );
      if (room)
        await submitJson(
          `/api/rooms/${room.id}/status`,
          "PATCH",
          { status: "open", note: "维修完成，恢复可用" },
          "座位已恢复为可预约",
        );
    }
    if (name === "import-csv") $("#csv-input")?.click();
    if (name === "download-csv") {
      const blob = new Blob(
        [
          "name,student_no,phone,password\n林知夏,2024010201,13800002051,123456aa\n",
        ],
        { type: "text/csv;charset=utf-8" },
      );
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "students.csv.example";
      a.click();
    }
    if (name === "refresh") {
      await refresh();
      toast("数据已刷新");
    }
    return;
  }
  const booking = event.target.closest("[data-booking-id]");
  if (booking) {
    await submitJson(
      `/api/bookings/${booking.dataset.bookingId}/status?status=${booking.dataset.status}`,
      "PATCH",
      {},
      "预约状态已更新",
    );
  }
  const classroomEdit = event.target.closest("[data-classroom-edit]");
  if (classroomEdit)
    classroomForm(
      state.classrooms.find(
        (item) => item.id === Number(classroomEdit.dataset.classroomEdit),
      ),
    );
  const classroomDelete = event.target.closest("[data-classroom-delete]");
  if (classroomDelete && confirm("确定删除这间教室吗？")) {
    await submitJson(
      `/api/classrooms/${classroomDelete.dataset.classroomDelete}`,
      "DELETE",
      {},
      "教室已删除",
    );
  }
  const userEdit = event.target.closest("[data-user-edit]");
  if (userEdit)
    studentForm(
      state.users.find((item) => item.id === Number(userEdit.dataset.userEdit)),
    );
  const userDelete = event.target.closest("[data-user-delete]");
  if (userDelete && confirm("确定删除该学生吗？关联预约存在时无法删除。"))
    await submitJson(
      `/api/users/${userDelete.dataset.userDelete}`,
      "DELETE",
      {},
      "学生已删除",
    );
});
document.addEventListener("input", (event) => {
  const feedbackForm = event.target.closest?.("#feedback-form");
  if (feedbackForm) feedbackForm.dataset.dirty = "true";
  if (event.target.id === "seat-search") filterSeatCards();
  if (event.target.id === "booking-search")
    $("#booking-table-body").innerHTML = bookingRows(
      state.bookings.filter((item) =>
        `${item.user_name}${item.room_name}`
          .toLowerCase()
          .includes(event.target.value.toLowerCase()),
      ),
    );
  if (event.target.id === "user-search")
    $("#user-table-body").innerHTML = userRows(
      state.users.filter((item) =>
        `${item.name}${item.student_no}`
          .toLowerCase()
          .includes(event.target.value.toLowerCase()),
      ),
    );
});
document.addEventListener("change", async (event) => {
  if (event.target.id === "student-blacklist-status") {
    const restricted = event.target.value === "true";
    const untilInput = $("#student-blacklist-until");
    const reasonInput = $("#student-blacklist-reason");
    if (untilInput) {
      untilInput.disabled = !restricted;
      if (!untilInput.disabled && !untilInput.value) {
        const defaultDate = new Date();
        defaultDate.setDate(defaultDate.getDate() + 7);
        untilInput.value = defaultDate.toISOString().slice(0, 10);
      }
    }
    if (reasonInput) reasonInput.disabled = !restricted;
  }
  if (event.target.id === "seat-status") filterSeatCards();
  if (event.target.id === "booking-status")
    $("#booking-table-body").innerHTML = bookingRows(
      event.target.value === "all"
        ? state.bookings
        : state.bookings.filter((item) => item.status === event.target.value),
    );
  if (event.target.id === "classroom-status") {
    const value = event.target.value;
    document
      .querySelectorAll(".classroom-card")
      .forEach((card) => (card.style.display = ""));
    if (value !== "all")
      state.classrooms.forEach((room, index) => {
        if (room.status !== value)
          document.querySelectorAll(".classroom-card")[index].style.display =
            "none";
      });
  }
  if (event.target.id === "csv-input") {
    const file = event.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try {
      const result = await api("/api/users/import", {
        method: "POST",
        body: form,
      });
      await refresh();
      toast(result.message);
    } catch (error) {
      toast(error.message);
    }
    event.target.value = "";
  }
});
function boot() {
  if (state.session) {
    renderShell();
    refresh();
  } else renderLogin();
  setInterval(() => {
    if (state.session) refresh(true);
  }, 10000);
}
const csvInput = document.createElement("input");
csvInput.type = "file";
csvInput.id = "csv-input";
csvInput.accept = ".csv";
csvInput.hidden = true;
document.body.appendChild(csvInput);
boot();
