import { McpJsonEditor } from "./mcp-editor.js?v=20260804k";

const SESSION_KEY = "relay-admin-token";

const state = {
  devices: [],
  audit: [],
  view: "config",
  selectedDeviceId: null,
  selectedAgentId: null,
  deviceDetail: null,
  scriptExamples: null,
  /** Last successfully saved mcp.json text (restore target). */
  lastSavedMcpText: "",
  /** Bumped to invalidate in-flight refresh races. */
  dataEpoch: 0,
  /** Bumped on each successful save; refresh must not apply older GETs. */
  savedGen: 0,
  savingMcp: false,
  authed: false,
  /** "password" = built-in login gate; "access" = reverse proxy is the gate. */
  authMode: "password",
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

function getSessionToken() {
  return sessionStorage.getItem(SESSION_KEY);
}

function setSessionToken(token) {
  sessionStorage.setItem(SESSION_KEY, token);
}

function clearSessionToken() {
  sessionStorage.removeItem(SESSION_KEY);
}

function showLogin(errorMsg = "") {
  state.authed = false;
  const gate = $("#login-gate");
  const shell = $("#app-shell");
  gate?.classList.remove("hidden");
  shell?.classList.add("hidden");
  const err = $("#login-error");
  if (err) {
    if (errorMsg) {
      err.textContent = errorMsg;
      err.classList.remove("hidden");
    } else {
      err.textContent = "";
      err.classList.add("hidden");
    }
  }
  const pass = $("#login-pass");
  if (pass) pass.value = "";
  $("#login-user")?.focus();
}

function showApp() {
  state.authed = true;
  $("#login-gate")?.classList.add("hidden");
  $("#app-shell")?.classList.remove("hidden");
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const admin = getSessionToken();
  if (admin && !headers.Authorization) {
    headers.Authorization = `Bearer ${admin}`;
  }
  const res = await fetch(path, {
    ...opts,
    headers,
  });
  if (res.status === 401 || res.status === 503) {
    const text = await res.text();
    if (path.startsWith("/api/v1/") && !path.includes("/devices/me") && !path.includes("/devices/register") && !path.includes("/auth/login")) {
      const err = new Error(`${res.status}: ${text}`);
      err.adminAuth = true;
      throw err;
    }
    throw new Error(`${res.status}: ${text}`);
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

async function login(username, password) {
  const res = await fetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(res.status === 401 ? "用户名或密码错误" : text);
  }
  const data = await res.json();
  setSessionToken(data.token);
  return data;
}

async function logout() {
  const token = getSessionToken();
  try {
    if (token) {
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
    }
  } catch {
    /* ignore */
  }
  clearSessionToken();
  showLogin();
}

async function ensureSession() {
  if (state.authMode === "access") {
    showApp();
    return true;
  }
  if (state.authed && getSessionToken()) return true;
  const token = getSessionToken();
  if (!token) {
    showLogin();
    return false;
  }
  try {
    await api("/api/v1/auth/me");
    showApp();
    return true;
  } catch {
    clearSessionToken();
    showLogin("登录已过期，请重新登录");
    return false;
  }
}

function fmtTime(v) {
  if (!v) return "—";
  try {
    return new Date(v).toLocaleString("zh-CN");
  } catch {
    return v;
  }
}

function setView(name) {
  state.view = name;
  $$(".nav button[data-view]").forEach((b) => {
    const on = b.dataset.view === name;
    b.classList.toggle("active", on);
    if (on) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  $$("main > section").forEach((s) => s.classList.toggle("hidden", s.id !== `view-${name}`));
}

function esc(v) {
  return String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function applyTheme(theme) {
  document.body.dataset.theme = theme;
  localStorage.setItem("relay-theme", theme);
  const btn = $("#btn-theme");
  const night = theme === "night";
  if (btn) {
    btn.textContent = night ? "主题：夜间" : "主题：日间";
    btn.setAttribute("aria-pressed", night ? "true" : "false");
  }
  McpJsonEditor.setNight(night);
}

function mcpGet() {
  return McpJsonEditor.getValue();
}

function mcpSet(text) {
  McpJsonEditor.setValue(text ?? "");
}

function mcpSetReadOnly(ro) {
  const el = $("#mcp-editor");
  McpJsonEditor.setReadOnly(ro);
  el?.classList.toggle("is-disabled", !!ro);
}

function renderOverview() {
  const online = state.devices.filter((d) => d.online).length;
  const set = (id, v) => {
    const el = $(id);
    if (el) el.textContent = v;
  };
  set("#stat-devices", state.devices.length);
  set("#stat-online", online);

  const rows = state.devices
    .slice()
    .sort((a, b) =>
      String(b.last_seen_at || b.last_sync_at || "").localeCompare(String(a.last_seen_at || a.last_sync_at || ""))
    )
    .slice(0, 8)
    .map(
      (d) => `<tr>
      <td class="mono">${esc(d.device_id)}</td>
      <td>${esc(d.hostname || "—")}</td>
      <td>${(d.targets || []).map((t) => `<span class="badge">${esc(t)}</span>`).join(" ")}</td>
      <td>${fmtTime(d.last_sync_at)}</td>
    </tr>`
    )
    .join("");

  const box = $("#overview-devices");
  if (box) {
    box.innerHTML = rows
      ? `<table><thead><tr><th>设备</th><th>主机</th><th>Agent</th><th>最近同步</th></tr></thead><tbody>${rows}</tbody></table>`
      : `<p class="muted pad">暂无已注册设备</p>`;
  }
}

function pushStatusBadge(d) {
  const lp = d.last_push;
  if (!lp) return "";
  const cls =
    lp.status === "acked"
      ? "push-ok"
      : lp.status === "failed"
        ? "push-fail"
        : lp.status === "sent" || lp.status === "queued"
          ? "push-pending"
          : "";
  const label =
    lp.status === "acked"
      ? "已推送"
      : lp.status === "failed"
        ? "推送失败"
        : lp.status === "sent"
          ? "已发送"
          : lp.status === "queued"
            ? "待推送"
            : lp.status;
  return `<span class="badge push-badge ${cls}">${esc(label)}</span>`;
}

function presenceDot(online) {
  const tip = online
    ? "WebSocket 在线（mcp-relay connect / watch）"
    : "离线：本机需运行 mcp-relay connect 或 watch 才会显示绿点";
  return `<span class="presence-dot ${online ? "online" : "offline"}" title="${tip}"></span>`;
}

function renderDevicesList() {
  const countEl = $("#device-count");
  const listEl = $("#devices-list");
  if (!countEl || !listEl) return;
  countEl.textContent = `${state.devices.length}`;
  if (!state.devices.length) {
    listEl.innerHTML =
      `<p class="muted pad">暂无设备。运行 <span class="mono">mcp-relay init --url … && mcp-relay sync</span></p>`;
    return;
  }
  listEl.innerHTML = state.devices
    .map((d) => {
      const active = d.device_id === state.selectedDeviceId ? "active" : "";
      const agents = (d.targets || []).map((t) => `<span class="badge">${esc(t)}</span>`).join(" ");
      return `<div class="device-row ${active}" role="option" aria-selected="${active ? "true" : "false"}">
        <button type="button" class="device-row-main" data-select-device="${esc(d.device_id)}">
          <div class="device-row-top">
            <span class="device-row-title">${presenceDot(d.online)}<strong class="mono">${esc(d.hostname || d.device_id)}</strong></span>
          </div>
          <div class="device-row-meta muted">${esc(d.device_id)}</div>
          <div class="device-row-agents">${agents || '<span class="muted">无 Agent</span>'}</div>
          <div class="device-row-meta">${pushStatusBadge(d)} <span class="muted">最近可见 ${fmtTime(d.last_seen_at || d.last_sync_at)}</span></div>
        </button>
        <div class="device-row-actions">
          <button class="btn btn-danger btn-xs" type="button" data-del-device="${esc(d.device_id)}" title="删除后客户端须重新 init --url">删除</button>
        </div>
      </div>`;
    })
    .join("");
}

function currentAgent() {
  const agents = state.deviceDetail?.agents || [];
  return agents.find((a) => a.id === state.selectedAgentId) || null;
}

function renderAgentsList() {
  const d = state.deviceDetail;
  const list = $("#agents-list");
  const count = $("#agent-count");
  if (!d) {
    count.textContent = "";
    list.innerHTML = `<p class="muted pad">请先选择左侧设备</p>`;
    return;
  }
  const agents = d.agents || [];
  count.textContent = `${agents.length}`;
  if (!agents.length) {
    list.innerHTML = `<p class="muted pad">未识别到 Agent，请在该设备重新 register</p>`;
    return;
  }
  list.innerHTML = agents
    .map((a) => {
      const active = a.id === state.selectedAgentId ? "active" : "";
      const on = a.enabled !== false;
      const n = Object.keys(a.mcp_document?.mcpServers || {}).length;
      return `<button type="button" class="agent-row ${active}" data-select-agent="${esc(a.id)}" role="option" aria-selected="${active ? "true" : "false"}">
        <div class="agent-row-top">
          <strong>${esc(a.id)}</strong>
          <span class="badge ${on ? "ok" : "off"}">${on ? "已启用" : "已停用"}</span>
        </div>
        <div class="agent-row-meta muted mono">${esc(a.detected?.path || "—")}</div>
        <div class="agent-row-meta muted">mcp.json 含 ${n} 个服务</div>
      </button>`;
    })
    .join("");
}

function savedMcpTextForAgent(agent) {
  const doc = agent?.mcp_document || { mcpServers: {} };
  return JSON.stringify(doc, null, 2);
}

function isMcpDirty() {
  if (!state.selectedAgentId) return false;
  return mcpGet() !== state.lastSavedMcpText;
}

function updateMcpChrome(agent, { dirty = false } = {}) {
  const enabled = $("#agent-enabled");
  const saveBtn = $("#btn-mcp-save");
  const resetBtn = $("#btn-mcp-reset");
  const formatBtn = $("#btn-mcp-format");
  $("#mcp-title").textContent = `${agent.id} · mcp.json`;
  $("#mcp-path").textContent = agent.detected?.path || `同步目标：${agent.id}`;
  $("#mcp-hint").textContent = dirty
    ? "有未保存修改。点「刷新」不会覆盖编辑器内容。"
    : agent.mcp_servers
      ? "CodeMirror · Tab 缩进 · Ctrl/⌘+Shift+F 格式化。未保存编辑可「恢复上次保存」。"
      : "尚未保存固定文档（空文档）。编辑后保存才会下发；格式化：Ctrl/⌘+Shift+F。";
  mcpSetReadOnly(false);
  enabled.disabled = false;
  saveBtn.disabled = !!state.savingMcp;
  resetBtn.disabled = !!state.savingMcp;
  if (formatBtn) formatBtn.disabled = !!state.savingMcp;
}

function renderMcpEditor({ force = true } = {}) {
  const enabled = $("#agent-enabled");
  const saveBtn = $("#btn-mcp-save");
  const resetBtn = $("#btn-mcp-reset");
  const formatBtn = $("#btn-mcp-format");
  const agent = currentAgent();
  if (!state.deviceDetail || !agent) {
    $("#mcp-title").textContent = "mcp.json";
    $("#mcp-path").textContent = "—";
    $("#mcp-hint").textContent = "右侧是该 Agent 的完整 MCP 文档，不按单个服务拆开编辑。";
    if (force) {
      mcpSet("");
      state.lastSavedMcpText = "";
    }
    mcpSetReadOnly(true);
    enabled.checked = false;
    enabled.disabled = true;
    saveBtn.disabled = true;
    resetBtn.disabled = true;
    if (formatBtn) formatBtn.disabled = true;
    return;
  }

  const text = savedMcpTextForAgent(agent);
  const dirty = isMcpDirty();

  if (force) {
    state.lastSavedMcpText = text;
    mcpSet(text);
    enabled.checked = agent.enabled !== false;
    updateMcpChrome(agent, { dirty: false });
    return;
  }

  // Soft refresh: never clobber in-progress edits; never rewrite lastSaved while dirty.
  if (dirty || state.savingMcp) {
    updateMcpChrome(agent, { dirty: true });
    return;
  }

  state.lastSavedMcpText = text;
  if (mcpGet() !== text) mcpSet(text);
  enabled.checked = agent.enabled !== false;
  updateMcpChrome(agent, { dirty: false });
}

function renderConfigPanels({ forceEditor = true } = {}) {
  renderDevicesList();
  renderAgentsList();
  renderMcpEditor({ force: forceEditor });
}

async function selectDevice(deviceId) {
  if (state.selectedDeviceId && state.selectedDeviceId !== deviceId && isMcpDirty()) {
    if (!confirm("当前有未保存修改，切换设备将丢失。继续？")) return;
  }
  state.selectedDeviceId = deviceId;
  state.selectedAgentId = null;
  renderDevicesList();
  try {
    state.deviceDetail = await api(`/api/v1/devices/${encodeURIComponent(deviceId)}`);
    const agents = state.deviceDetail.agents || [];
    if (agents.length) state.selectedAgentId = agents[0].id;
    renderAgentsList();
    renderMcpEditor({ force: true });
  } catch (err) {
    toast(err.message);
  }
}

function selectAgent(agentId) {
  if (state.selectedAgentId && state.selectedAgentId !== agentId && isMcpDirty()) {
    if (!confirm("当前 Agent 有未保存修改，切换将丢失。继续？")) return;
  }
  state.selectedAgentId = agentId;
  renderAgentsList();
  renderMcpEditor({ force: true });
}

async function saveMcpDocument() {
  const agentId = state.selectedAgentId;
  const deviceId = state.selectedDeviceId;
  if (!agentId || !deviceId || state.savingMcp) return;

  let doc;
  try {
    doc = JSON.parse(mcpGet());
  } catch (err) {
    toast(`JSON 无效：${err.message}`);
    return;
  }
  const mcpServers = doc.mcpServers ?? doc.mcp_servers ?? null;
  if (!mcpServers || typeof mcpServers !== "object" || Array.isArray(mcpServers)) {
    toast('需要格式 {"mcpServers": { ... }}');
    return;
  }

  const pretty = JSON.stringify({ mcpServers }, null, 2);
  const enabled = $("#agent-enabled").checked;

  state.savingMcp = true;
  $("#btn-mcp-save").disabled = true;
  $("#btn-mcp-reset").disabled = true;
  $("#btn-mcp-format").disabled = true;
  // Freeze editor to the payload we are about to persist.
  state.lastSavedMcpText = pretty;
  mcpSet(pretty);

  try {
    const detail = await api(`/api/v1/devices/${encodeURIComponent(deviceId)}/agents`, {
      method: "PATCH",
      body: JSON.stringify({
        agent_config: {
          [agentId]: {
            enabled,
            mcp_document: { mcpServers },
          },
        },
      }),
    });

    state.savedGen += 1;
    state.deviceDetail = detail;
    // Re-assert local agent view from what we saved (ignore response key order).
    const agent = (detail.agents || []).find((a) => a.id === agentId);
    if (agent) {
      agent.mcp_servers = mcpServers;
      agent.mcp_document = { mcpServers };
      agent.enabled = enabled;
    }
    state.lastSavedMcpText = pretty;
    mcpSet(pretty);
    renderAgentsList();
    updateMcpChrome(agent || { id: agentId, mcp_servers: mcpServers }, { dirty: false });
    toast(`已保存 ${agentId}`);
  } catch (err) {
    toast(err.message);
    throw err;
  } finally {
    state.savingMcp = false;
    $("#btn-mcp-save").disabled = false;
    $("#btn-mcp-reset").disabled = false;
    $("#btn-mcp-format").disabled = false;
  }
}

function restoreLastSavedMcp() {
  const agentId = state.selectedAgentId;
  if (!agentId) return;
  if (!state.lastSavedMcpText) {
    toast("没有可恢复的已保存内容");
    return;
  }
  if (mcpGet() === state.lastSavedMcpText) {
    toast("已是上次保存内容");
    return;
  }
  mcpSet(state.lastSavedMcpText);
  toast(`已恢复 ${agentId} 上次保存`);
}

function formatMcpDocument() {
  if (McpJsonEditor.format()) toast("已格式化");
  else toast("JSON 无效，无法格式化");
}

function renderAudit() {
  $("#audit-table").innerHTML = `
    <table>
      <thead><tr><th>时间</th><th>操作</th><th>详情</th></tr></thead>
      <tbody>
        ${state.audit
          .map(
            (a) => `<tr>
          <td>${fmtTime(a.created_at)}</td>
          <td><span class="badge">${esc(a.action)}</span></td>
          <td class="mono">${esc(JSON.stringify(a.detail || {}))}</td>
        </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
}

async function refresh() {
  // Never touch the editor while saving or when there are unsaved edits.
  const skipEditor = state.savingMcp || isMcpDirty();
  const epoch = ++state.dataEpoch;
  const genAtStart = state.savedGen;

  if (!(await ensureSession())) return;

  let health, devices, audit;
  try {
    [health, devices, audit] = await Promise.all([
      api("/health"),
      api("/api/v1/devices"),
      api("/api/v1/audit?limit=40"),
    ]);
  } catch (err) {
    if (err.adminAuth) {
      clearSessionToken();
      showLogin("登录已失效，请重新登录");
      return;
    }
    throw err;
  }
  if (epoch !== state.dataEpoch) return;

  state.devices = devices;
  state.audit = audit;
  const healthLine = $("#health-line");
  if (healthLine) healthLine.textContent = `接口 ${health.status} · ${fmtTime(health.time)}`;

  if (state.selectedDeviceId && !skipEditor) {
    try {
      const keepAgent = state.selectedAgentId;
      const detail = await api(`/api/v1/devices/${encodeURIComponent(state.selectedDeviceId)}`);
      if (epoch !== state.dataEpoch) return;
      // A save completed while we were fetching — keep the post-save view.
      if (state.savingMcp || isMcpDirty() || genAtStart !== state.savedGen) {
        renderDevicesList();
        return;
      }
      state.deviceDetail = detail;
      const agents = state.deviceDetail.agents || [];
      if (keepAgent && agents.some((a) => a.id === keepAgent)) {
        state.selectedAgentId = keepAgent;
      } else {
        state.selectedAgentId = agents[0]?.id || null;
      }
    } catch (err) {
      console.warn(err);
      state.selectedDeviceId = null;
      state.deviceDetail = null;
    }
  }

  if (epoch !== state.dataEpoch) return;
  renderConfigPanels({ forceEditor: false });
  try {
    renderOverview();
    renderAudit();
  } catch (err) {
    console.warn(err);
  }
}

async function runScript(dryRun) {
  const script = $("#script-editor").value;
  const format = $("#script-format").value || null;
  const data = await api("/api/v1/scripts/apply", {
    method: "POST",
    body: JSON.stringify({ script, format, dry_run: dryRun }),
  });
  $("#script-result-meta").textContent = dryRun
    ? `试运行 · 匹配 ${data.matched} 台`
    : `已应用 ${data.applied} / 匹配 ${data.matched}`;
  $("#script-result").textContent = JSON.stringify(data, null, 2);
  toast(dryRun ? `试运行：匹配 ${data.matched} 台设备` : `已应用：${data.applied} 台`);
  if (!dryRun) await refresh();
}

function clamp(n, min, max) {
  return Math.min(max, Math.max(min, n));
}

function initResizableColumns() {
  const root = $("#device-workspace");
  if (!root) return;

  const KEY = "relay-config-cols";
  const MIN = { devices: 160, agents: 160 };
  const DEFAULT = { devices: 260, agents: 240 };

  let widths = { ...DEFAULT };
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (saved && Number.isFinite(saved.devices) && Number.isFinite(saved.agents)) {
      widths = { devices: saved.devices, agents: saved.agents };
    }
  } catch {
    /* ignore */
  }

  function apply() {
    root.style.setProperty("--col-devices", `${widths.devices}px`);
    root.style.setProperty("--col-agents", `${widths.agents}px`);
  }

  function persist() {
    localStorage.setItem(KEY, JSON.stringify(widths));
  }

  function maxFor(which) {
    const total = root.clientWidth;
    const other = which === "devices" ? widths.agents : widths.devices;
    const splits = 16;
    const mcpMin = 240;
    return Math.max(MIN[which], total - other - splits - mcpMin);
  }

  apply();

  root.querySelectorAll(".col-split").forEach((split) => {
    const which = split.dataset.split;
    if (!which || !(which in widths)) return;

    const startDrag = (clientX) => {
      const startX = clientX;
      const startW = widths[which];
      split.classList.add("is-active");
      root.classList.add("is-resizing");

      const onMove = (ev) => {
        const x = ev.touches ? ev.touches[0].clientX : ev.clientX;
        widths[which] = clamp(startW + (x - startX), MIN[which], maxFor(which));
        apply();
        if (ev.cancelable) ev.preventDefault();
      };
      const onUp = () => {
        split.classList.remove("is-active");
        root.classList.remove("is-resizing");
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
        window.removeEventListener("touchmove", onMove);
        window.removeEventListener("touchend", onUp);
        persist();
      };

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
      window.addEventListener("touchmove", onMove, { passive: false });
      window.addEventListener("touchend", onUp);
    };

    split.addEventListener("pointerdown", (e) => {
      if (e.button != null && e.button !== 0) return;
      split.setPointerCapture?.(e.pointerId);
      startDrag(e.clientX);
      e.preventDefault();
    });

    split.addEventListener("keydown", (e) => {
      const step = e.shiftKey ? 32 : 12;
      if (e.key === "ArrowLeft") {
        widths[which] = clamp(widths[which] - step, MIN[which], maxFor(which));
        apply();
        persist();
        e.preventDefault();
      } else if (e.key === "ArrowRight") {
        widths[which] = clamp(widths[which] + step, MIN[which], maxFor(which));
        apply();
        persist();
        e.preventDefault();
      } else if (e.key === "Home") {
        widths[which] = DEFAULT[which];
        apply();
        persist();
        e.preventDefault();
      }
    });
  });

  window.addEventListener("resize", () => {
    widths.devices = clamp(widths.devices, MIN.devices, maxFor("devices"));
    widths.agents = clamp(widths.agents, MIN.agents, maxFor("agents"));
    apply();
  });
}

function wire() {
  // Login first — must work even if the editor fails to mount.
  $("#login-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    const user = $("#login-user")?.value?.trim() || "";
    const pass = $("#login-pass")?.value || "";
    const btn = e.target.querySelector("button[type=submit]");
    if (btn) btn.disabled = true;
    try {
      await login(user, pass);
      showApp();
      toast("登录成功");
      await refresh();
    } catch (err) {
      showLogin(err.message || "登录失败");
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  initResizableColumns();

  const saved = localStorage.getItem("relay-theme");
  applyTheme(saved === "night" ? "night" : "day");
  $("#btn-theme")?.addEventListener("click", () => {
    applyTheme(document.body.dataset.theme === "night" ? "day" : "night");
  });
  $("#btn-admin-logout")?.addEventListener("click", () => {
    logout().then(() => toast("已退出"));
  });

  $$(".nav button[data-view]").forEach((b) =>
    b.addEventListener("click", () => setView(b.dataset.view))
  );

  const refreshToast = () => refresh().then(() => toast("已刷新"));
  $("#btn-refresh")?.addEventListener("click", refreshToast);
  $("#btn-refresh-config")?.addEventListener("click", refreshToast);
  // No auto-refresh: stale GETs were racing first saves and clearing the editor.

  $("#btn-release")?.addEventListener("click", async () => {
    const r = await api("/api/v1/releases?changelog=ui", { method: "POST" });
    toast(`已发布 ${r.id}`);
    await refresh();
  });

  $("#btn-script-parse")?.addEventListener("click", async () => {
    const script = $("#script-editor").value;
    const format = $("#script-format").value || null;
    const data = await api("/api/v1/scripts/parse", {
      method: "POST",
      body: JSON.stringify({ script, format }),
    });
    $("#script-result-meta").textContent = data.ok
      ? `解析成功 · ${data.ops_count} 条操作 · ${data.source}`
      : "解析失败";
    $("#script-result").textContent = JSON.stringify(data, null, 2);
  });
  $("#btn-script-dry")?.addEventListener("click", () => runScript(true).catch((e) => toast(e.message)));
  $("#btn-script-apply")?.addEventListener("click", async () => {
    if (!confirm("将脚本应用到匹配设备？这会写入设备的 Agent 配置。")) return;
    try {
      await runScript(false);
    } catch (e) {
      toast(e.message);
    }
  });
  $("#btn-script-example-yaml")?.addEventListener("click", async () => {
    if (!state.scriptExamples) state.scriptExamples = await api("/api/v1/scripts/examples");
    $("#script-editor").value = state.scriptExamples.yaml;
    $("#script-format").value = "yaml";
  });
  $("#btn-script-example-dsl")?.addEventListener("click", async () => {
    if (!state.scriptExamples) state.scriptExamples = await api("/api/v1/scripts/examples");
    $("#script-editor").value = state.scriptExamples.dsl;
    $("#script-format").value = "dsl";
  });

  $("#btn-mcp-save")?.addEventListener("click", () => saveMcpDocument().catch((e) => toast(e.message)));
  $("#btn-mcp-reset")?.addEventListener("click", () => restoreLastSavedMcp());
  $("#btn-mcp-format")?.addEventListener("click", () => formatMcpDocument());

  document.addEventListener("click", async (e) => {
    const selDev = e.target.closest("[data-select-device]");
    if (selDev) {
      await selectDevice(selDev.dataset.selectDevice);
      return;
    }
    const openCfg = e.target.closest("[data-open-config]");
    if (openCfg) {
      setView("config");
      await selectDevice(openCfg.dataset.openConfig);
      return;
    }
    const delDev = e.target.closest("[data-del-device]");
    if (delDev) {
      e.preventDefault();
      e.stopPropagation();
      const id = delDev.dataset.delDevice;
      if (
        !confirm(
          `删除设备 ${id}？\n\n将立刻作废其 token 并断开连接。该机器需重新执行：\nmcp-relay init --url <服务端URL>\nmcp-relay sync`
        )
      ) {
        return;
      }
      await api(`/api/v1/devices/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (state.selectedDeviceId === id) {
        state.selectedDeviceId = null;
        state.selectedAgentId = null;
        state.deviceDetail = null;
      }
      toast(`已删除 ${id}`);
      await refresh();
      renderConfigPanels();
      return;
    }
    const selAgent = e.target.closest("[data-select-agent]");
    if (selAgent) {
      selectAgent(selAgent.dataset.selectAgent);
      return;
    }
  });
}

async function boot() {
  // Ask the server which auth mode is active so the login gate can be skipped
  // when a reverse proxy (Cloudflare Access) is the identity gate.
  try {
    const cfg = await api("/api/v1/auth/config");
    state.authMode = cfg.mode === "access" ? "access" : "password";
  } catch {
    state.authMode = "password";
  }
  if (state.authMode === "access") {
    const gate = $("#login-gate");
    if (gate) gate.classList.add("hidden");
    const logoutBtn = $("#btn-admin-logout");
    if (logoutBtn) logoutBtn.classList.add("hidden");
    showApp();
  }
}

wire();
boot().then(() => {
  try {
    const editorEl = $("#mcp-editor");
    if (editorEl) McpJsonEditor.mount(editorEl);
  } catch (err) {
    console.error("mcp editor mount failed", err);
  }
  return refresh();
}).catch((err) => {
  const healthLine = $("#health-line");
  if (healthLine) healthLine.textContent = `加载失败：${err.message}`;
  toast(err.message);
});
