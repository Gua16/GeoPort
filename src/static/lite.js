"use strict";
const $ = id => document.getElementById(id);
let saved = null;
let busy = false;
let scanning = false;
const states = {idle: "未启动", processing: "处理中…", simulating: "模拟中", failed: "失败"};
const pointText = point => point ? `${point.lat.toFixed(6)}, ${point.lng.toFixed(6)}` : "尚未保存";

function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").dataset.context = $("preferences-panel").hidden ? "workspace" : "preferences";
  $("operation-status").hidden = Boolean(message);
  $("notice").classList.toggle("error", error);
  $("notice").classList.toggle("processing", message === "处理中…");
}
async function api(path, method = "GET", data) {
  const response = await fetch(path, {method, headers: data === undefined ? {} : {"Content-Type": "application/json"}, body: data === undefined ? undefined : JSON.stringify(data)});
  const text = await response.text();
  let payload;
  try { payload = JSON.parse(text); } catch (_) { payload = {message: text}; }
  // Settings includes the last device error as state, even on a successful read.
  if (!response.ok || ((payload.error || payload.Error) && path !== "/api/settings")) {
    const error = new Error(payload.error || payload.Error || (payload.developer_mode_required ? "请先开启设备的开发者模式" : `操作失败（HTTP ${response.status}）`));
    error.payload = payload;
    throw error;
  }
  return payload;
}
function controls() {
  const connected = Boolean(saved?.device_connection);
  const locked = busy || saved?.location_status === "processing";
  document.querySelectorAll("button,input,select").forEach(element => { element.disabled = element.hasAttribute("data-ui-only") ? false : locked; });
  $("workspace-panel").setAttribute("aria-busy", locked ? "true" : "false");
  $("refresh").disabled = locked || scanning;
  $("connect").disabled = locked || scanning || !$("device").value || connected;
  $("disconnect").disabled = locked || !connected;
  $("disconnect").hidden = !connected;
  $("connect").hidden = connected;
  $("device").disabled = locked || scanning || connected;
  $("random").disabled = $("apply-base").disabled = locked || !connected || !saved?.base_location;
  $("stop").disabled = locked || !connected;
}
function render() {
  if (!saved) return;
  $("base-display").textContent = pointText(saved.base_location);
  $("current-display").textContent = saved.current_location ? pointText(saved.current_location) : "尚未应用 / 已停止";
  $("location-status").textContent = states[saved.location_status] || saved.location_status;
  $("device-status").textContent = saved.device_connection ? `已连接 · ${saved.device_connection.connType} · iOS ${saved.device_connection.ios_version}` : "尚未连接设备";
  const connected = Boolean(saved.device_connection);
  $("device-summary").textContent = connected ? "已连接" : "未连接";
  $("device-badge").textContent = connected ? "已连接" : "未连接";
  $("device-badge").classList.toggle("connected", connected);
  $("radius-summary").textContent = saved.random_radius_m;
  const operation = $("operation-status");
  operation.classList.toggle("success", saved.location_status === "simulating");
  operation.classList.toggle("failed", saved.location_status === "failed");
  operation.textContent = saved.location_status === "simulating" ? "最近一次定位已成功应用" :
    saved.location_status === "processing" ? "正在等待设备确认，请稍候…" :
    saved.location_status === "failed" ? (saved.error || "定位失败，请检查设备连接。") :
    connected && saved.base_location ? "设备已就绪，点击按钮应用定位。" : "连接设备并保存基准后，即可应用定位。";
  const history = saved.base_history || [];
  const signature = JSON.stringify(history);
  if ($("base-history").dataset.entries !== signature) {
    $("base-history").replaceChildren(new Option(history.length ? "选择历史基准" : "尚无历史记录", ""));
    history.forEach(point => $("base-history").add(new Option(pointText(point), JSON.stringify(point))));
    $("base-history").dataset.entries = signature;
  }
  controls();
}
async function sync(initial = false) {
  saved = await api("/api/settings");
  if (initial) {
    if (saved.base_location) {
      $("latitude").value = saved.base_location.lat;
      $("longitude").value = saved.base_location.lng;
    }
    $("radius").value = saved.random_radius_m;
    $("startup-mode").value = saved.ui_mode;
    if (saved.settings_warning) notice(saved.settings_warning, true);
  }
  render();
}
async function run(work, success) {
  if (busy || saved?.location_status === "processing") return;
  busy = true;
  controls();
  notice("处理中…");
  try {
    await work();
    if (success) notice(success);
    if (success?.startsWith("基准坐标已保存")) $("draft-indicator").textContent = "";
  } catch (error) {
    notice(error.message, true);
    if (error.payload?.developer_mode_required) $("developer-help").hidden = false;
  } finally {
    try { await sync(); } catch (error) { notice(error.message, true); }
    busy = false;
    controls();
  }
}
async function scan() {
  if (scanning || busy) return;
  scanning = true;
  controls();
  try {
    const devices = await api("/list_devices");
    $("device").replaceChildren(new Option("选择设备", ""));
    Object.entries(devices).forEach(([udid, connections]) => Object.entries(connections).forEach(([connection, entries]) => {
      entries.forEach(info => {
        const connType = connection === "Wifi" ? "Network" : connection === "Manual Wifi" ? "Manual" : connection;
        const data = {udid, connType, ios_version: info.ProductVersion};
        $("device").add(new Option(`${info.DeviceName || udid} · ${connection} · iOS ${info.ProductVersion}`, JSON.stringify(data)));
      });
    }));
    if ($("device").options.length === 1) notice("未发现设备。请连接并解锁 iPhone，确认配对和 USB 服务可用。");
    else $("device").selectedIndex = 1;
  } catch (error) {
    $("device").replaceChildren(new Option("设备扫描失败", ""));
    notice(`设备扫描失败：${error.message}`, true);
  } finally { scanning = false; controls(); }
}
$("device").addEventListener("change", controls);
$("refresh").addEventListener("click", scan);
$("connect").addEventListener("click", () => run(async () => {
  await api("/connect_device", "POST", JSON.parse($("device").value));
  $("developer-help").hidden = true;
}, "设备连接成功。尚未应用任何坐标。"));
$("disconnect").addEventListener("click", () => run(() => api("/api/device/disconnect", "POST", {}), "已停止模拟并断开设备。"));
$("enable-developer").addEventListener("click", () => run(() => api("/enable_developer_mode", "POST", JSON.parse($("device").value)), "请在设备上完成确认，再点击连接。"));
$("base-form").addEventListener("submit", event => {
  event.preventDefault();
  run(() => api("/api/base-location", "PUT", {lat: Number($("latitude").value), lng: Number($("longitude").value)}), "基准坐标已保存；尚未应用到设备。" );
});
$("base-history").addEventListener("change", () => {
  if (!$("base-history").value) return;
  const point = JSON.parse($("base-history").value);
  $("latitude").value = point.lat;
  $("longitude").value = point.lng;
  notice("历史坐标已填入，请点击保存基准。尚未应用到设备。");
});
$("radius").addEventListener("change", () => {
  if (!$("radius").reportValidity()) return;
  run(() => api("/api/settings", "PUT", {random_radius_m: Number($("radius").value)}), "偏移半径已保存。" )
    .finally(() => { if (saved) $("radius").value = saved.random_radius_m; });
});
$("startup-mode").addEventListener("change", () => run(() => api("/api/settings", "PUT", {ui_mode: $("startup-mode").value}), "下次启动界面已保存。"));
$("random").addEventListener("click", () => run(() => api("/api/location/apply", "POST", {mode: "random"}), "已应用一次随机偏移，基准坐标保持不变。"));
$("apply-base").addEventListener("click", () => run(() => api("/api/location/apply", "POST", {mode: "base"}), "设备定位已恢复至基准坐标。"));
$("stop").addEventListener("click", () => run(() => api("/stop_location", "POST", {}), "模拟定位已停止，基准坐标保持不变。"));
controls();
sync(true).then(scan).catch(error => notice(error.message, true));
// Only local state polling. No map, CDN, telemetry or Internet API is loaded.
const statePoll = setInterval(() => { if (!busy) sync().catch(error => notice(error.message, true)); }, 2000);
$("quit").addEventListener("click", async () => {
  if (busy || saved?.location_status === "processing") return;
  busy = true;
  controls();
  notice("正在停止模拟并退出…");
  try {
    await api("/exit", "POST", {});
    clearInterval(statePoll);
    document.querySelectorAll("button,input,select").forEach(element => { element.disabled = true; });
    notice("服务已退出，请关闭此页面。");
    window.GeoPortPage?.exited();
  } catch (error) {
    notice(error.message, true);
    busy = false;
    controls();
  }
});

function activateTab(selected, focus = false) {
  if ($("notice").dataset.context !== selected) {
    $("notice").textContent = "";
    $("operation-status").hidden = false;
  }
  for (const name of ["workspace", "preferences"]) {
    const active = name === selected;
    const tab = $(name + "-tab");
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    tab.classList.toggle("selected", active);
    $(name + "-panel").hidden = !active;
  }
  if (selected === "preferences") $("preferences-panel").insertBefore($("notice"), $("preferences-panel").children[1]);
  else $("operation-status").before($("notice"));
  if (focus) $(selected + "-tab").focus();
}
for (const name of ["workspace", "preferences"]) {
  const tab = $(name + "-tab");
  tab.addEventListener("click", () => activateTab(name));
  tab.addEventListener("keydown", event => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const next = event.key === "Home" ? "workspace" : event.key === "End" ? "preferences" : name === "workspace" ? "preferences" : "workspace";
      activateTab(next, true);
    }
  });
}
for (const name of ["latitude", "longitude"]) {
  $(name).addEventListener("input", () => {
    const changed = !saved?.base_location || Number($("latitude").value) !== saved.base_location.lat || Number($("longitude").value) !== saved.base_location.lng;
    $("draft-indicator").textContent = changed ? "尚未保存" : "";
  });
}
