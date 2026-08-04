const state = {
  servers: [],
  bindings: [],
  devices: [],
  skills: [],
  audit: [],
  view: "config",
  selectedDeviceId: null,
  selectedAgentId: null,
  deviceDetail: null,
  scriptExamples: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  if (res.status === 204) return null;
  return res.json();
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
  btn.textContent = night ? "主题：夜间" : "主题：日间";
  btn.setAttribute("aria-pressed", night ? "true" : "false");
}

function renderOverview() {
  $("#stat-servers").textContent = state.servers.length;
  $("#stat-bindings").textContent = state.bindings.length;
  $("#stat-devices").textContent = state.devices.length;
  $("#stat-skills").textContent = state.skills.length;

  const rows = state.devices
    .slice()
    .sort((a, b) =>
      String(b.last_seen_at || b.last_sync_at || "").localeCompare(String(a.last_seen_at || a.last_sync_at || ""))
    )
    .slice(0, 8)
    .map(
      (d) => `<tr>
      <td class="mono">${esc(d.device_id)}</td>
      <td>${esc(d.profile)}</td>
      <td>${(d.targets || []).map((t) => `<span class="badge">${esc(t)}</span>`).join(" ")}</td>
      <td>${fmtTime(d.last_sync_at)}</td>
    </tr>`
    )
    .join("");

  $("#overview-devices").innerHTML = rows
    ? `<table><thead><tr><th>设备</th><th>Profile</th><th>Agent</th><th>最近同步</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<p class="muted pad">暂无已注册设备</p>`;
}

function renderServers() {
  $("#servers-table").innerHTML = `
    <table>
      <thead><tr><th>标识</th><th>传输</th><th>默认配置</th><th>标签</th><th></th></tr></thead>
      <tbody>
        ${state.servers
          .map(
            (s) => `<tr>
          <td><strong>${esc(s.id)}</strong><div class="muted">${esc(s.display_name || "")}</div></td>
          <td><span class="badge">${esc(s.transport)}</span></td>
          <td class="mono">${esc(JSON.stringify(s.default))}</td>
          <td>${(s.tags || []).map((t) => `<span class="badge">${esc(t)}</span>`).join(" ")}</td>
          <td>
            <button class="btn" data-edit-server="${esc(s.id)}" type="button">编辑</button>
            <button class="btn btn-danger" data-del-server="${esc(s.id)}" type="button">删除</button>
          </td>
        </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
}

function renderDevicesTable() {
  const el = $("#devices-table");
  if (!el) return;
  if (!state.devices.length) {
    el.innerHTML = `<p class="muted pad">暂无设备。在客户端运行 <span class="mono">relay-agent register</span></p>`;
    return;
  }
  el.innerHTML = `
    <table>
      <thead><tr><th>设备 ID</th><th>主机名</th><th>Profile</th><th>Agent</th><th>版本</th><th>最近同步</th><th></th></tr></thead>
      <tbody>
        ${state.devices
          .map(
            (d) => `<tr>
          <td class="mono">${esc(d.device_id)}</td>
          <td>${esc(d.hostname || "—")}</td>
          <td>${esc(d.profile)}</td>
          <td>${(d.targets || []).map((t) => `<span class="badge">${esc(t)}</span>`).join(" ")}</td>
          <td>${esc(d.agent_version || "—")}</td>
          <td>${fmtTime(d.last_sync_at)}</td>
          <td><button class="btn" type="button" data-open-config="${esc(d.device_id)}">去配置</button></td>
        </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
}

function renderDevicesList() {
  $("#device-count").textContent = `${state.devices.length}`;
  if (!state.devices.length) {
    $("#devices-list").innerHTML =
      `<p class="muted pad">暂无设备。运行 <span class="mono">relay-agent register</span></p>`;
    return;
  }
  $("#devices-list").innerHTML = state.devices
    .map((d) => {
      const active = d.device_id === state.selectedDeviceId ? "active" : "";
      const agents = (d.targets || []).map((t) => `<span class="badge">${esc(t)}</span>`).join(" ");
      return `<button type="button" class="device-row ${active}" data-select-device="${esc(d.device_id)}" role="option" aria-selected="${active ? "true" : "false"}">
        <div class="device-row-top">
          <strong class="mono">${esc(d.hostname || d.device_id)}</strong>
          <span class="badge">${esc(d.profile)}</span>
        </div>
        <div class="device-row-meta muted">${esc(d.device_id)}</div>
        <div class="device-row-agents">${agents || '<span class="muted">无 Agent</span>'}</div>
        <div class="device-row-meta muted">最近可见 ${fmtTime(d.last_seen_at || d.last_sync_at)}</div>
      </button>`;
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

function renderMcpEditor() {
  const editor = $("#mcp-editor");
  const enabled = $("#agent-enabled");
  const saveBtn = $("#btn-mcp-save");
  const resetBtn = $("#btn-mcp-reset");
  const agent = currentAgent();
  if (!state.deviceDetail || !agent) {
    $("#mcp-title").textContent = "mcp.json";
    $("#mcp-path").textContent = "—";
    $("#mcp-hint").textContent = "右侧是该 Agent 的完整 MCP 文档，不按单个服务拆开编辑。";
    editor.value = "";
    editor.disabled = true;
    enabled.checked = false;
    enabled.disabled = true;
    saveBtn.disabled = true;
    resetBtn.disabled = true;
    return;
  }
  const doc = agent.mcp_document || { mcpServers: {} };
  $("#mcp-title").textContent = `${agent.id} · mcp.json`;
  $("#mcp-path").textContent = agent.detected?.path || `同步目标：${agent.id}`;
  $("#mcp-hint").textContent = agent.mcp_servers
    ? "已固定整份 mcpServers（保存会覆盖）。重置可回到 Profile 默认渲染。"
    : "当前为 Profile 绑定渲染结果。保存后以编辑器内容为准下发。";
  editor.value = JSON.stringify(doc, null, 2);
  editor.disabled = false;
  enabled.disabled = false;
  enabled.checked = agent.enabled !== false;
  saveBtn.disabled = false;
  resetBtn.disabled = false;
}

function renderConfigPanels() {
  renderDevicesList();
  renderAgentsList();
  renderMcpEditor();
}

async function selectDevice(deviceId) {
  state.selectedDeviceId = deviceId;
  state.selectedAgentId = null;
  renderDevicesList();
  try {
    state.deviceDetail = await api(`/api/v1/devices/${encodeURIComponent(deviceId)}`);
    const agents = state.deviceDetail.agents || [];
    if (agents.length) state.selectedAgentId = agents[0].id;
    renderAgentsList();
    renderMcpEditor();
  } catch (err) {
    toast(err.message);
  }
}

function selectAgent(agentId) {
  state.selectedAgentId = agentId;
  renderAgentsList();
  renderMcpEditor();
}

async function saveMcpDocument() {
  const agentId = state.selectedAgentId;
  if (!agentId || !state.selectedDeviceId) return;
  let doc;
  try {
    doc = JSON.parse($("#mcp-editor").value);
  } catch (err) {
    toast(`JSON 无效：${err.message}`);
    return;
  }
  const mcpServers = doc.mcpServers ?? doc.mcp_servers ?? (doc && typeof doc === "object" ? doc : null);
  if (!mcpServers || typeof mcpServers !== "object" || Array.isArray(mcpServers)) {
    toast('需要格式 {"mcpServers": { ... }}');
    return;
  }
  const enabled = $("#agent-enabled").checked;
  state.deviceDetail = await api(`/api/v1/devices/${encodeURIComponent(state.selectedDeviceId)}/agents`, {
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
  toast(`已保存 ${agentId}`);
  renderAgentsList();
  renderMcpEditor();
}

async function resetMcpDocument() {
  const agentId = state.selectedAgentId;
  if (!agentId || !state.selectedDeviceId) return;
  if (!confirm(`清除 ${agentId} 的固定 mcp.json，恢复为 Profile 默认？`)) return;
  state.deviceDetail = await api(`/api/v1/devices/${encodeURIComponent(state.selectedDeviceId)}/agents`, {
    method: "PATCH",
    body: JSON.stringify({
      agent_config: {
        [agentId]: {
          enabled: $("#agent-enabled").checked,
          mcp_servers: null,
          servers: {},
        },
      },
    }),
  });
  toast(`已重置 ${agentId}`);
  renderAgentsList();
  renderMcpEditor();
}

function renderSkills() {
  $("#skills-table").innerHTML = `
    <table>
      <thead><tr><th>标识</th><th>版本</th><th>路径</th><th>目标 Agent</th><th>Profiles</th></tr></thead>
      <tbody>
        ${state.skills
          .map(
            (s) => `<tr>
          <td class="mono">${esc(s.id)}</td>
          <td>${esc(s.version)}</td>
          <td class="mono">${esc(s.path)}</td>
          <td class="mono">${esc(Object.keys(s.targets || {}).join(", "))}</td>
          <td>${(s.profiles || []).map((p) => `<span class="badge">${esc(p)}</span>`).join(" ")}</td>
        </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
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
  const [health, servers, bindings, devices, skills, audit] = await Promise.all([
    api("/health"),
    api("/api/v1/logical-servers"),
    api("/api/v1/bindings"),
    api("/api/v1/devices"),
    api("/api/v1/skill-packs"),
    api("/api/v1/audit?limit=40"),
  ]);
  state.servers = servers;
  state.bindings = bindings;
  state.devices = devices;
  state.skills = skills;
  state.audit = audit;
  const healthLine = $("#health-line");
  if (healthLine) healthLine.textContent = `接口 ${health.status} · ${fmtTime(health.time)}`;
  renderOverview();
  renderServers();
  renderDevicesTable();
  renderSkills();
  renderAudit();
  if (state.selectedDeviceId) {
    const keepAgent = state.selectedAgentId;
    state.deviceDetail = await api(`/api/v1/devices/${encodeURIComponent(state.selectedDeviceId)}`);
    const agents = state.deviceDetail.agents || [];
    if (keepAgent && agents.some((a) => a.id === keepAgent)) {
      state.selectedAgentId = keepAgent;
    } else {
      state.selectedAgentId = agents[0]?.id || null;
    }
  }
  renderConfigPanels();
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
  initResizableColumns();

  const saved = localStorage.getItem("relay-theme");
  applyTheme(saved === "night" ? "night" : "day");
  $("#btn-theme").addEventListener("click", () => {
    applyTheme(document.body.dataset.theme === "night" ? "day" : "night");
  });

  $$(".nav button[data-view]").forEach((b) =>
    b.addEventListener("click", () => setView(b.dataset.view))
  );

  const refreshToast = () => refresh().then(() => toast("已刷新"));
  $("#btn-refresh")?.addEventListener("click", refreshToast);
  $("#btn-refresh-devices")?.addEventListener("click", refreshToast);
  $("#btn-refresh-config")?.addEventListener("click", refreshToast);

  $("#btn-release")?.addEventListener("click", async () => {
    const r = await api("/api/v1/releases?changelog=ui", { method: "POST" });
    toast(`已发布 ${r.id}`);
    await refresh();
  });

  $("#server-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      id: fd.get("id").trim(),
      display_name: fd.get("display_name").trim() || null,
      transport: fd.get("transport"),
      default: JSON.parse(fd.get("default_json")),
      tags: String(fd.get("tags") || "")
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
    };
    await api("/api/v1/logical-servers", { method: "POST", body: JSON.stringify(body) });
    toast(`已保存 ${body.id}`);
    e.target.reset();
    await refresh();
  });

  $("#btn-preview")?.addEventListener("click", async () => {
    const profile = $("#preview-profile").value;
    const target = $("#preview-target").value;
    const data = await api(
      `/api/v1/preview?profile=${encodeURIComponent(profile)}&target=${encodeURIComponent(target)}`
    );
    $("#preview-meta").textContent = `${profile} × ${target} · ${Object.keys(data.servers || {}).length} 个服务`;
    $("#preview-out").textContent = JSON.stringify(data, null, 2);
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
  $("#btn-mcp-reset")?.addEventListener("click", () => resetMcpDocument().catch((e) => toast(e.message)));

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
    const selAgent = e.target.closest("[data-select-agent]");
    if (selAgent) {
      selectAgent(selAgent.dataset.selectAgent);
      return;
    }
    const editS = e.target.closest("[data-edit-server]");
    if (editS) {
      const s = state.servers.find((x) => x.id === editS.dataset.editServer);
      if (!s) return;
      const f = $("#server-form");
      f.id.value = s.id;
      f.display_name.value = s.display_name || "";
      f.transport.value = s.transport;
      f.default_json.value = JSON.stringify(s.default || {}, null, 2);
      f.tags.value = (s.tags || []).join(",");
      setView("servers");
    }
    const delS = e.target.closest("[data-del-server]");
    if (delS) {
      if (!confirm(`删除 MCP 服务 ${delS.dataset.delServer}？`)) return;
      await api(`/api/v1/logical-servers/${encodeURIComponent(delS.dataset.delServer)}`, { method: "DELETE" });
      toast("已删除");
      await refresh();
    }
  });
}

wire();
refresh().catch((err) => {
  const healthLine = $("#health-line");
  if (healthLine) healthLine.textContent = `加载失败：${err.message}`;
  toast(err.message);
});
