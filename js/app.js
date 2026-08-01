/* AI 顶会信息看板 - 前端逻辑
 * 数据来源: window.CONF_DATA (由 data-inline.js 注入，保证 file:// 双击可用)
 */

(function () {
  "use strict";

  var DATA = window.CONF_DATA || { conferences: [] };
  var STATE = {
    status: "all",     // all | open | closed
    sort: "deadline",  // deadline | name
  };

  // 类别 -> 卡片标签文本
  var CAT_LABELS = {
    "AI-ML": "AI/ML",
    "CV": "CV",
    "NLP": "NLP",
    "DM-IR": "DM/IR",
    "RO": "Robotics",
  };
  function catLabelOf(c) {
    return CAT_LABELS[c.category] || c.category;
  }

  // ---------- 工具函数 ----------

  function fmtDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.getFullYear() + "-" +
      String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0");
  }

  function fmtDateAoE(iso) {
    // 截止时间统一存为 AoE(UTC-12) 的 ISO 串(带 -12:00 偏移)。
    // 直接取字符串里的日期分量，避免 new Date() 换算到本地时区后
    // 日期 ±1 天(如 UTC+8 用户会把 AoE 5/6 的截止看成 5/7)。
    if (!iso) return "—";
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso));
    if (m) return m[1] + "-" + m[2] + "-" + m[3];
    return fmtDate(iso);
  }

  function daysUntil(iso) {
    if (!iso) return null;
    var d = new Date(iso);
    if (isNaN(d)) return null;
    var ms = d.getTime() - Date.now();
    // 用 floor 而非 ceil: 截止当天(尚未到点)算 0 天 → "今天截止";
    // 一旦过了截止点即变负 → "已截止"。ceil 会让当天显示"剩1天"、
    // 且截止后 24 小时内仍误显示"今天截止"。
    return Math.floor(ms / 86400000);
  }

  function isPast(iso) {
    var days = daysUntil(iso);
    return days !== null && days < 0;
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------- 倒计时标签 ----------

  function countdownBadge(iso) {
    var days = daysUntil(iso);
    if (days === null) return '<span class="cd cd-none">—</span>';
    if (days < 0) return '<span class="cd cd-past">已截止</span>';
    if (days === 0) return '<span class="cd cd-urgent">今天截止</span>';
    var cls = days <= 7 ? "cd-urgent" : days <= 30 ? "cd-warn" : "cd-ok";
    return '<span class="cd ' + cls + '">剩 ' + days + ' 天</span>';
  }

  function urgencyColor(days) {
    if (days === null) return "#adb5bd";
    if (days < 0) return "#adb5bd";
    if (days <= 7) return "#e03131";
    if (days <= 30) return "#f08c00";
    return "#3b5bdb";
  }

  // ---------- 渲染: 顶部高亮区 ----------

  function renderUrgent() {
    var box = document.getElementById("urgent");
    var upcoming = DATA.conferences.filter(function (c) {
      var d = daysUntil(c.deadlines.submission);
      return d !== null && d >= 0;
    });
    upcoming.sort(function (a, b) {
      return daysUntil(a.deadlines.submission) - daysUntil(b.deadlines.submission);
    });
    var top3 = upcoming.slice(0, 3);

    if (top3.length === 0) {
      box.innerHTML = '<p class="empty">暂无即将截止的会议</p>';
      return;
    }

    box.innerHTML = top3.map(function (c) {
      var days = daysUntil(c.deadlines.submission);
      var color = urgencyColor(days);
      var catLabel = catLabelOf(c);
      return (
        '<div class="urgent-card" style="border-left-color:' + color + '">' +
        '<div class="urgent-head">' +
          '<span class="urgent-title">' + escapeHtml(c.title) + ' ' + c.year + '</span>' +
          '<span class="cat-tag cat-' + c.category + '">' + catLabel + '</span>' +
        '</div>' +
        '<div class="urgent-countdown" style="color:' + color + '">' +
          (days === 0 ? "今天" : days) +
          '<small>' + (days === 0 ? "截止" : "天") + '</small>' +
        '</div>' +
        '<div class="urgent-meta">' +
          '<div>投稿截止: <b>' + fmtDateAoE(c.deadlines.submission) + '</b></div>' +
          '<div>' + (c.place ? escapeHtml(c.place) : "地点待定") + '</div>' +
        '</div>' +
        '<a class="urgent-link" href="' + escapeHtml(c.link) + '" target="_blank">访问官网 →</a>' +
        '</div>'
      );
    }).join("");
  }

  // ---------- 渲染: 会议卡片 ----------

  function nodeRow(label, iso, confidence) {
    var days = daysUntil(iso);
    var stateCls = "node-future";
    if (days === null) stateCls = "node-none";
    else if (days < 0) stateCls = "node-past";
    else if (days <= 14) stateCls = "node-soon";

    var confMark = "";
    if (confidence === "medium" || confidence === "low") {
      confMark = ' <span class="conf-mark" title="此日期待确认">!</span>';
    }

    return (
      '<tr class="' + stateCls + '">' +
        '<td class="node-label">' + label + confMark + '</td>' +
        '<td class="node-date">' + fmtDateAoE(iso) + '</td>' +
        '<td class="node-cd">' + (days !== null && days >= 0 ? countdownBadge(iso) : "") + '</td>' +
      '</tr>'
    );
  }

  function renderCard(c) {
    var catLabel = catLabelOf(c);
    // 头部 ! 徽章只标记"有字段缺失或低置信度"的卡; medium 不算——
    // place 普遍由 ccf 补(永远 medium)、standalone 的 deadline 也统一 medium,
    // 若 medium 也触发, 每张卡都会亮 !, 警告就失去区分度了。
    // 单字段的 medium/low 仍由 nodeRow 里各自的 ! 标记。
    var hasMissing = Object.keys(c.confidence || {}).some(function (k) {
      return c.confidence[k] === "missing" || c.confidence[k] === "low";
    });
    if (!c.deadlines.submission || !c.deadlines.notification) hasMissing = true;
    if (!c.conference_start) hasMissing = true;

    var confDateStr = c.conference_start
      ? (c.conference_start + (c.conference_end && c.conference_end !== c.conference_start ? " ~ " + c.conference_end.slice(5) : ""))
      : "待定";

    var nodes = [
      ["摘要截止", c.deadlines.abstract, c.confidence.abstract],
      ["投稿截止", c.deadlines.submission, c.confidence.submission],
      ["Rebuttal 起", c.deadlines.rebuttal_start, c.confidence.rebuttal_start],
      ["Rebuttal 止", c.deadlines.rebuttal_end, c.confidence.rebuttal_end],
      ["结果通知", c.deadlines.notification, c.confidence.notification],
      ["Camera Ready", c.deadlines.camera_ready, c.confidence.camera_ready],
    ];

    return (
      '<div class="card cat-' + c.category + '">' +
        '<div class="card-head">' +
          '<div>' +
            '<span class="card-title">' + escapeHtml(c.title) + ' ' + c.year + '</span>' +
            '<span class="cat-tag cat-' + c.category + '">' + catLabel + '</span>' +
            (hasMissing ? '<span class="conf-mark conf-mark-head" title="部分信息待确认">!</span>' : "") +
          '</div>' +
          '<div class="card-sub">' + escapeHtml(c.full_name) + '</div>' +
        '</div>' +
        '<div class="card-meta">' +
          '<span>📅 ' + confDateStr + '</span>' +
          '<span>📍 ' + (c.place ? escapeHtml(c.place) : "地点待定") + '</span>' +
        '</div>' +
        '<div class="card-cd">' + countdownBadge(c.deadlines.submission) + '</div>' +
        '<table class="node-table">' +
          nodes.map(function (n) { return nodeRow(n[0], n[1], n[2]); }).join("") +
        '</table>' +
        '<a class="card-link" href="' + escapeHtml(c.link) + '" target="_blank">访问官网 →</a>' +
      '</div>'
    );
  }

  function renderBoard() {
    var list = DATA.conferences.slice();

    // 筛选
    list = list.filter(function (c) {
      if (STATE.status !== "all") {
        var open = c.deadlines.submission && !isPast(c.deadlines.submission);
        if (STATE.status === "open" && !open) return false;
        if (STATE.status === "closed" && open) return false;
      }
      return true;
    });

    // 排序
    list.sort(function (a, b) {
      if (STATE.sort === "name") {
        return a.title.localeCompare(b.title) || (a.year - b.year);
      }
      // deadline 排序: 投稿中(剩余天数升序) → 已截止(最近截止的靠前) → 无截止日期最后。
      // 不能用 Infinity + d：Infinity + 负数仍是 Infinity，两个已截止项相减得 NaN，
      // 且 null(-Infinity) 与 Infinity 运算也产生 NaN，导致排序不稳定。
      var da = daysUntil(a.deadlines.submission);
      var db = daysUntil(b.deadlines.submission);
      function cat(d) {
        if (d === null) return 2;   // 无截止日期
        return d < 0 ? 1 : 0;        // 已截止 : 投稿中
      }
      var ca = cat(da), cb = cat(db);
      if (ca !== cb) return ca - cb;
      if (ca === 0) return da - db;   // 投稿中: 剩余天数升序
      if (ca === 1) return db - da;   // 已截止: 越接近今天(d 越大)越靠前 → 降序
      return 0;                        // 都无截止日期: 保持原序
    });

    var board = document.getElementById("board");
    if (list.length === 0) {
      board.innerHTML = '<p class="empty">没有符合条件的会议</p>';
    } else {
      board.innerHTML = list.map(renderCard).join("");
    }
  }

  // ---------- 渲染: 头部信息 ----------

  function renderHeader() {
    var el = document.getElementById("updated");
    if (DATA.generated_at) {
      var d = new Date(DATA.generated_at);
      el.textContent = "数据更新于 " + fmtDate(DATA.generated_at) + " " +
        String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
    }
  }

  // ---------- 全量渲染 ----------

  function renderAll() {
    renderHeader();
    renderUrgent();
    renderBoard();
  }

  // ---------- 事件绑定 ----------

  function bindControls() {
    // 状态
    document.querySelectorAll("[data-filter-status]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        STATE.status = btn.getAttribute("data-filter-status");
        document.querySelectorAll("[data-filter-status]").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        renderBoard();
      });
    });
    // 排序
    document.getElementById("sort-select").addEventListener("change", function () {
      STATE.sort = this.value;
      renderBoard();
    });
  }

  // ---------- 启动 ----------

  function init() {
    renderAll();
    bindControls();
    // 每分钟刷新倒计时
    setInterval(function () {
      renderUrgent();
      renderBoard();
    }, 60000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
