const state = {
  servers: [],
  bindings: [],
  devices: [],
  skills: [],
  audit: [],
  view: "overview",
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
    return new Date(v).toLocaleString();
  } catch {
    return v;
  }
}

function setView(name) {
  state.view = name;
  $$(".nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $$("main > section").forEach((s) => s.classList.toggle("hidden", s.id !== `view-${name}`));
}

function renderOverview() {
  $("#stat-servers").textContent = state.servers.length;
  $("#stat-bindings").textContent = state.bindings.length;
  $("#stat-devices").textContent = state.devices.length;
  $("#stat-skills").textContent = state.skills.length;

  const rows = state.devices
    .slice()
    .sort((a, b) => String(b.last_sync_at || "").localeCompare(String(a.last_sync_at || "")))
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
    ? `<table><thead><tr><th>Device</th><th>Profile</th><th>Targets</th><th>Last sync</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<p class="muted" style="padding:1rem">尚无设备注册</p>`;
}

function renderServers() {
  const list = $("#logical-ids");
  list.innerHTML = state.servers.map((s) => `<option value="${esc(s.id)}"></option>`).join("");

  $("#servers-table").innerHTML = `
    <table>
      <thead><tr><th>ID</th><th>Transport</th><th>Default</th><th>Tags</th><th></th></tr></thead>
      <tbody>
        ${state.servers
          .map(
            (s) => `<tr>
          <td><strong>${esc(s.id)}</strong><div class="muted">${esc(s.display_name || "")}</div></td>
          <td><span class="badge">${esc(s.transport)}</span></td>
          <td class="mono">${esc(JSON.stringify(s.default))}</td>
          <td>${(s.tags || []).map((t) => `<span class="badge">${esc(t)}</span>`).join(" ")}</td>
          <td><button class="btn" data-edit-server="${esc(s.id)}" type="button">编辑</button>
              <button class="btn btn-danger" data-del-server="${esc(s.id)}" type="button">删除</button></td>
        </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
}

function renderBindings() {
  const pf = $("#filter-profile").value;
  const tf = $("#filter-target").value;
  const rows = state.bindings.filter(
    (b) => (!pf || b.profile === pf) && (!tf || b.target === tf)
  );
  $("#bindings-table").innerHTML = `
    <table>
      <thead><tr><th>Logical</th><th>Profile</th><th>Target</th><th>Enabled</th><th>Overrides</th><th></th></tr></thead>
      <tbody>
        ${rows
          .map(
            (b) => `<tr>
          <td class="mono">${esc(b.logical_id)}</td>
          <td>${esc(b.profile)}</td>
          <td>${esc(b.target)}</td>
          <td><span class="badge ${b.enabled ? "ok" : "off"}">${b.enabled ? "on" : "off"}</span></td>
          <td class="mono">${esc(JSON.stringify(b.overrides || {}))}</td>
          <td>
            <button class="btn" data-edit-binding="${b.id}" type="button">编辑</button>
            <button class="btn btn-danger" data-del-binding="${b.id}" type="button">删除</button>
          </td>
        </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
}

function renderDevices() {
  $("#devices-table").innerHTML = `
    <table>
      <thead><tr><th>Device</th><th>Host</th><th>Profile</th><th>Targets</th><th>Agent</th><th>Last sync</th><th>Release</th></tr></thead>
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
          <td class="mono">${esc(d.last_release_id || "—")}</td>
        </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
}

function renderSkills() {
  $("#skills-table").innerHTML = `
    <table>
      <thead><tr><th>ID</th><th>Version</th><th>Path</th><th>Targets</th><th>Profiles</th></tr></thead>
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
      <thead><tr><th>Time</th><th>Action</th><th>Detail</th></tr></thead>
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

function esc(v) {
  return String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
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
  $("#health-line").textContent = `API ${health.status} · ${fmtTime(health.time)}`;
  renderOverview();
  renderServers();
  renderBindings();
  renderDevices();
  renderSkills();
  renderAudit();
}

function wire() {
  $$(".nav button").forEach((b) =>
    b.addEventListener("click", () => setView(b.dataset.view))
  );
  $("#btn-refresh").addEventListener("click", () => refresh().then(() => toast("已刷新")));
  $("#btn-release").addEventListener("click", async () => {
    const r = await api("/api/v1/releases?changelog=ui", { method: "POST" });
    toast(`已发布 ${r.id}`);
    await refresh();
  });
  $("#filter-profile").addEventListener("change", renderBindings);
  $("#filter-target").addEventListener("change", renderBindings);

  $("#server-form").addEventListener("submit", async (e) => {
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

  $("#binding-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      logical_id: fd.get("logical_id").trim(),
      profile: fd.get("profile"),
      target: fd.get("target"),
      enabled: fd.get("enabled") === "on",
      overrides: JSON.parse(fd.get("overrides_json") || "{}"),
    };
    await api("/api/v1/bindings", { method: "POST", body: JSON.stringify(body) });
    toast("绑定已保存");
    await refresh();
  });

  $("#btn-preview").addEventListener("click", async () => {
    const profile = $("#preview-profile").value;
    const target = $("#preview-target").value;
    const data = await api(`/api/v1/preview?profile=${encodeURIComponent(profile)}&target=${encodeURIComponent(target)}`);
    $("#preview-meta").textContent = `${profile} × ${target} · ${Object.keys(data.servers || {}).length} servers`;
    $("#preview-out").textContent = JSON.stringify(data, null, 2);
  });

  document.addEventListener("click", async (e) => {
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
      if (!confirm(`删除逻辑 MCP ${delS.dataset.delServer}?`)) return;
      await api(`/api/v1/logical-servers/${encodeURIComponent(delS.dataset.delServer)}`, { method: "DELETE" });
      toast("已删除");
      await refresh();
    }
    const editB = e.target.closest("[data-edit-binding]");
    if (editB) {
      const b = state.bindings.find((x) => String(x.id) === editB.dataset.editBinding);
      if (!b) return;
      const f = $("#binding-form");
      f.logical_id.value = b.logical_id;
      f.profile.value = b.profile;
      f.target.value = b.target;
      f.enabled.checked = !!b.enabled;
      f.overrides_json.value = JSON.stringify(b.overrides || {}, null, 2);
      setView("bindings");
    }
    const delB = e.target.closest("[data-del-binding]");
    if (delB) {
      if (!confirm("删除该绑定?")) return;
      await api(`/api/v1/bindings/${encodeURIComponent(delB.dataset.delBinding)}`, { method: "DELETE" });
      toast("已删除绑定");
      await refresh();
    }
  });
}

wire();
refresh().catch((err) => {
  $("#health-line").textContent = `加载失败: ${err.message}`;
  toast(err.message);
});
