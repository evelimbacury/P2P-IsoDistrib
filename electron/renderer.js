const API_BASE = "http://127.0.0.1:8765/api";
let desktopContext = null;
let isSessionActive = false;
let pendingDownloadName = null;

const $ = (id) => document.getElementById(id);
const elements = {
  metricPeers: $("metric-peers"),
  metricFiles: $("metric-files"),
  metricLocal: $("metric-local"),
  actionFeedback: $("action-feedback"),
  actionFeedbackText: $("action-feedback-text"),
  publishFileTop: $("publish-file-top"),
  refreshState: $("refresh-state"),
  settingsModal: $("settings-modal"),
  closeSettings: $("close-settings-modal"),
  closeSettingsDone: $("close-settings-done"),
  toggleSettings: $("toggle-settings"),
  trackerHost: $("tracker-host"),
  trackerPort: $("tracker-port"),
  peerPort: $("peer-port"),
  sharedFolder: $("shared-folder"),
  downloadFolder: $("download-folder"),
  pickSharedFolder: $("pick-shared-folder"),
  pickDownloadFolder: $("pick-download-folder"),
  localIps: $("local-ips"),
  searchQuery: $("search-query"),
  searchButton: $("search-button"),
  searchResultsBody: $("search-results-body"),
  localFilesBody: $("local-files-body"),
  downloadList: $("download-list"),
  multiDownloads: $("multi-downloads"),
  uploadSpeedSpan: $("upload-speed"),
  peerStatusSpan: $("peer-status"),
  localIpDisplay: $("local-ip-display"),
  peerPortDisplay: $("peer-port-display"),
  libraryFilter: $("library-filter"),
  logsBody: $("logs-body"),
  clearLogsBtn: $("clear-logs"),
};

let allLogs = [];

function setActionFeedback(level, text) {
  if (!elements.actionFeedback || !elements.actionFeedbackText) return;
  elements.actionFeedback.className = `action-feedback ${level || ""}`.trim();
  elements.actionFeedback.classList.remove("hidden");
  elements.actionFeedbackText.textContent = text;
}

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`);
  return res.json();
}

async function apiPost(path, payload = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (!res.ok) {
    throw new Error(body.error || "Erro na requisicao");
  }
  return body;
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(1)} ${units[index]}`;
}

function formatETA(seconds) {
  if (!seconds || seconds === Infinity) return "--";
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  if (hrs > 0) return `${hrs}h ${mins}m`;
  if (mins > 0) return `${mins}m ${secs}s`;
  return `${secs}s`;
}

function addSystemMessage(level, text, keepInLogs = true) {
  if (!keepInLogs) return;
  const timestamp = new Date().toLocaleTimeString();
  allLogs.unshift({ timestamp, level, text });
  if (allLogs.length > 200) {
    allLogs.pop();
  }
  renderLogs();
}

function renderLogs() {
  if (!elements.logsBody) return;
  if (!allLogs.length) {
    elements.logsBody.innerHTML = '<tr><td colspan="3" class="empty-cell">Nenhum log registrado.</td></tr>';
    return;
  }

  elements.logsBody.innerHTML = allLogs.map((log) => `
    <tr class="level-${log.level}">
      <td>${log.timestamp}</td>
      <td>${String(log.level || "info").toUpperCase()}</td>
      <td>${log.text}</td>
    </tr>
  `).join("");
}

function renderSearchResult(searchResult) {
  const body = elements.searchResultsBody;
  if (!body) return;
  body.innerHTML = "";

  if (!searchResult?.peers?.length) {
    body.innerHTML = '<tr><td colspan="4" class="empty-cell">Nenhum resultado encontrado.</td></tr>';
    return;
  }

  searchResult.peers.forEach((peer) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><i class="fas fa-file-iso"></i> ${searchResult.file_info.name}</td>
      <td>${formatBytes(searchResult.file_info.size)}</td>
      <td>${peer.ip}:${peer.port}</td>
      <td><button class="download-btn" data-filename="${searchResult.file_info.name}"><i class="fas fa-download"></i> Baixar</button></td>
    `;
    row.querySelector(".download-btn")?.addEventListener("click", async (event) => {
      event.stopPropagation();
      await downloadFile(searchResult.file_info.name);
    });
    body.appendChild(row);
  });
}

function renderLocalFiles(files) {
  const body = elements.localFilesBody;
  if (!body) return;
  const filter = (elements.libraryFilter?.value || "").toLowerCase();
  const filtered = files.filter((file) => file.name.toLowerCase().includes(filter));
  body.innerHTML = filtered.length ? "" : '<tr><td colspan="3" class="empty-cell">Nenhum arquivo encontrado.</td></tr>';
  filtered.forEach((file) => {
    body.insertAdjacentHTML("beforeend", `<tr><td><i class="fas fa-file-iso"></i> ${file.name}</td><td>${formatBytes(file.size)}</td><td>${(file.sha256 || "").slice(0, 16)}...</td></tr>`);
  });
}

function renderDownloadsMulti(downloads) {
  const container = elements.multiDownloads;
  if (!container) return;
  if (!downloads?.length && !pendingDownloadName) {
    container.innerHTML = '<div class="empty-cell" style="text-align:center;">Nenhum download ativo.</div>';
    if (elements.uploadSpeedSpan) {
      elements.uploadSpeedSpan.innerHTML = '<i class="fas fa-arrow-up"></i> Upload: 0 B/s';
    }
    return;
  }

  let totalUpload = 0;
  const cards = [];
  if (pendingDownloadName) {
    cards.push(`
      <div class="download-item pending">
        <div class="download-meta"><span>${pendingDownloadName}</span><span>Preparando download...</span></div>
        <div class="download-bar"><div class="download-fill" style="width: 8%"></div></div>
      </div>
    `);
  }

  const activeHtml = downloads.map((download) => {
    if (download.status === "downloading") {
      pendingDownloadName = null;
      const etaSec = download.size_bytes && download.speed_bytes_per_second
        ? (download.size_bytes - download.downloaded_bytes) / download.speed_bytes_per_second
        : 0;
      totalUpload += (download.upload_speed || 0);
      return `
        <div class="download-item">
          <div class="download-meta"><span>${download.filename}</span><span>${formatBytes(download.speed_bytes_per_second || 0)}/s | ETA ${formatETA(etaSec)}</span></div>
          <div class="download-bar"><div class="download-fill" style="width: ${download.percent || 0}%"></div></div>
        </div>
      `;
    }
    if (download.status === "completed") {
      return `<div class="download-item completed">Concluido: ${download.filename}</div>`;
    }
    return "";
  }).join("");

  container.innerHTML = `${cards.join("")}${activeHtml}` || '<div class="empty-cell">Aguardando...</div>';
  if (elements.uploadSpeedSpan) {
    elements.uploadSpeedSpan.innerHTML = `<i class="fas fa-arrow-up"></i> Upload: ${formatBytes(totalUpload)}/s`;
  }
}

function renderDownloadHistory(downloads) {
  const list = elements.downloadList;
  if (!list) return;
  if (!downloads?.length) {
    list.innerHTML = '<li class="empty-cell">Nenhum download concluido.</li>';
    return;
  }

  const completed = downloads.filter((download) => download.status === "completed").slice(-8).reverse();
  if (!completed.length) {
    list.innerHTML = '<li class="empty-cell">Nenhum download concluido.</li>';
    return;
  }

  list.innerHTML = completed.map((download) => `<li>${download.filename} | ${download.percent || 100}% | concluido</li>`).join("");
}

function renderState(state) {
  const session = state.session || {};
  const network = state.network || { peer_count: 0, published_file_count: 0 };
  const localFiles = state.local_files || [];
  const downloads = state.downloads || [];
  const searchResult = state.search_result;
  const config = state.config || {};
  const messages = state.messages || [];

  isSessionActive = session.is_connected || session.offline_mode;
  if (elements.metricPeers) elements.metricPeers.textContent = String(network.peer_count || 0);
  if (elements.metricFiles) elements.metricFiles.textContent = String(network.published_file_count || 0);
  if (elements.metricLocal) elements.metricLocal.textContent = String(localFiles.length);
  if (elements.peerStatusSpan) {
    elements.peerStatusSpan.innerHTML = isSessionActive
      ? '<i class="fas fa-circle" style="color:#5ed89f"></i> Sessao local pronta'
      : '<i class="fas fa-circle" style="color:#aaa"></i> Sessao local inativa';
  }
  if (elements.localIpDisplay) {
    elements.localIpDisplay.innerHTML = `<i class="fas fa-ip"></i> IP: ${desktopContext?.localIps?.[0] || "--"}`;
  }
  if (elements.peerPortDisplay) {
    elements.peerPortDisplay.innerHTML = `<i class="fas fa-plug"></i> Porta: ${config.peer_port || "--"}`;
  }

  if (elements.trackerHost && document.activeElement !== elements.trackerHost) elements.trackerHost.value = config.tracker_host || desktopContext?.preferredTrackerHost || "";
  if (elements.trackerPort && document.activeElement !== elements.trackerPort) elements.trackerPort.value = config.tracker_port || desktopContext?.preferredTrackerPort || "";
  if (elements.peerPort && document.activeElement !== elements.peerPort) elements.peerPort.value = config.peer_port || "";
  if (elements.sharedFolder && document.activeElement !== elements.sharedFolder) elements.sharedFolder.value = config.shared_folder || "";
  if (elements.downloadFolder && document.activeElement !== elements.downloadFolder) elements.downloadFolder.value = config.download_folder || "";

  messages.slice(-10).forEach((message) => {
    if (!allLogs.some((log) => log.level === message.level && log.text === message.text)) {
      addSystemMessage(message.level, message.text, true);
    }
  });

  if (downloads.some((download) => download.status === "completed")) {
    const latestCompleted = [...downloads].reverse().find((download) => download.status === "completed");
    if (latestCompleted) {
      setActionFeedback("success", `Download concluido: ${latestCompleted.filename}`);
    }
  }

  renderSearchResult(searchResult);
  renderLocalFiles(localFiles);
  renderDownloadsMulti(downloads);
  renderDownloadHistory(downloads);
}

async function refreshState() {
  try {
    const state = await apiGet("/state");
    renderState(state);
  } catch (error) {
    addSystemMessage("error", `Falha ao atualizar: ${error.message}`, true);
    if (elements.peerStatusSpan) {
      elements.peerStatusSpan.innerHTML = '<i class="fas fa-circle"></i> API offline';
    }
  }
}

async function hydrateDesktopContext() {
  try {
    desktopContext = await window.desktopBridge.getDesktopContext();
  } catch (_error) {
    desktopContext = null;
  }

  if (desktopContext?.localIps && elements.localIps) {
    elements.localIps.innerHTML = `<i class="fas fa-network-wired"></i> IPs locais: ${desktopContext.localIps.join(" | ")}`;
  }
}

async function startSession() {
  try {
    await apiPost("/session/start", {
      tracker_host: elements.trackerHost?.value.trim(),
      tracker_port: parseInt(elements.trackerPort?.value, 10) || 5000,
      peer_port: parseInt(elements.peerPort?.value, 10) || 6000,
      shared_folder: elements.sharedFolder?.value.trim() || undefined,
      download_folder: elements.downloadFolder?.value.trim() || undefined,
    });
    addSystemMessage("success", "Sessao local iniciada.", true);
    await refreshState();
  } catch (error) {
    addSystemMessage("error", error.message, true);
  }
}

async function performSearch() {
  const query = elements.searchQuery?.value.trim();
  if (!query) return;
  if (elements.searchButton) {
    elements.searchButton.innerHTML = '<i class="fas fa-spinner fa-pulse"></i>';
  }
  try {
    await apiPost("/search", { query });
    await refreshState();
  } finally {
    if (elements.searchButton) {
      elements.searchButton.innerHTML = '<i class="fas fa-search"></i> Pesquisar';
    }
  }
}

async function publishFile() {
  const filepath = await window.desktopBridge.pickIsoFile();
  if (!filepath) return;
  await apiPost("/publish", { path: filepath });
  setActionFeedback("success", "ISO compartilhada com sucesso.");
  await refreshState();
}

async function downloadFile(filename) {
  if (!isSessionActive) {
    addSystemMessage("error", "Sessao local inativa.", true);
    setActionFeedback("error", "A sessao local precisa estar pronta antes de baixar.");
    return;
  }
  try {
    pendingDownloadName = filename;
    setActionFeedback("warning", `Download solicitado: ${filename}`);
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((content) => content.classList.remove("active"));
    document.querySelector('.tab[data-tab="network"]')?.classList.add("active");
    document.getElementById("tab-network")?.classList.add("active");
    await apiPost("/download", { filename });
    addSystemMessage("success", `Download iniciado: ${filename}`, true);
    setActionFeedback("warning", `Download iniciado: ${filename}`);
    await refreshState();
  } catch (error) {
    pendingDownloadName = null;
    addSystemMessage("error", `Erro: ${error.message}`, true);
    setActionFeedback("error", `Falha ao iniciar download: ${error.message}`);
  }
}

function bindEvents() {
  elements.publishFileTop?.addEventListener("click", publishFile);
  elements.searchButton?.addEventListener("click", performSearch);
  elements.refreshState?.addEventListener("click", refreshState);
  elements.pickSharedFolder?.addEventListener("click", async () => {
    const folder = await window.desktopBridge.pickFolder();
    if (folder && elements.sharedFolder) elements.sharedFolder.value = folder;
  });
  elements.pickDownloadFolder?.addEventListener("click", async () => {
    const folder = await window.desktopBridge.pickFolder();
    if (folder && elements.downloadFolder) elements.downloadFolder.value = folder;
  });
  elements.libraryFilter?.addEventListener("input", refreshState);
  elements.toggleSettings?.addEventListener("click", () => elements.settingsModal?.classList.remove("hidden"));
  elements.closeSettings?.addEventListener("click", () => elements.settingsModal?.classList.add("hidden"));
  elements.closeSettingsDone?.addEventListener("click", () => elements.settingsModal?.classList.add("hidden"));
  elements.clearLogsBtn?.addEventListener("click", () => {
    allLogs = [];
    renderLogs();
    addSystemMessage("info", "Logs limpos manualmente.", true);
  });
  elements.searchQuery?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      performSearch();
    }
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;
      document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
      tab.classList.add("active");
      document.querySelectorAll(".tab-content").forEach((content) => content.classList.remove("active"));
      const activeTab = document.getElementById(`tab-${target}`);
      if (activeTab) activeTab.classList.add("active");
      if (target === "logs") renderLogs();
      if (target === "library") refreshState();
    });
  });
}

function init() {
  bindEvents();
  hydrateDesktopContext().finally(async () => {
    await startSession();
    await refreshState();
    setInterval(refreshState, 2500);
  });
}

window.addEventListener("DOMContentLoaded", init);
