const { app, BrowserWindow, dialog, ipcMain, clipboard } = require("electron");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");

const API_PORT = process.env.DESKTOP_API_PORT || "8765";
const API_HOST = process.env.DESKTOP_API_HOST || "127.0.0.1";
const API_BASE = `http://${API_HOST}:${API_PORT}`;

let backendProcess = null;
let backendExitedDuringStartup = false;
let backendStartupError = null;

function getProjectRoot() {
  return path.resolve(__dirname, "..");
}

function getRuntimeDir() {
  const runtimeDir = path.join(getProjectRoot(), "desktop_runtime");
  fs.mkdirSync(runtimeDir, { recursive: true });
  return runtimeDir;
}

function getLogFilePath() {
  return path.join(getRuntimeDir(), "electron-main.log");
}

function getTrackerConfigPath() {
  return path.join(getRuntimeDir(), "tracker-config.json");
}

function appendLog(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  try {
    fs.appendFileSync(getLogFilePath(), line, "utf8");
  } catch (error) {
    console.error("Failed to write Electron log:", error);
  }
}

function getLocalIPv4Addresses() {
  const interfaces = os.networkInterfaces();
  const results = [];
  Object.values(interfaces).forEach((entries) => {
    (entries || []).forEach((entry) => {
      if (!entry || entry.internal || entry.family !== "IPv4") {
        return;
      }
      if (!results.includes(entry.address)) {
        results.push(entry.address);
      }
    });
  });
  return results;
}

function readTrackerConfig() {
  const configPath = getTrackerConfigPath();
  if (!fs.existsSync(configPath)) {
    return null;
  }

  try {
    return JSON.parse(fs.readFileSync(configPath, "utf8"));
  } catch (error) {
    appendLog(`[tracker-config read error] ${error.stack || error.message}`);
    return null;
  }
}

function getDesktopContext() {
  const trackerConfig = readTrackerConfig();
  const localIps = getLocalIPv4Addresses();
  const preferredTrackerHost = trackerConfig?.trackerHost || process.env.TRACKER_HOST || "127.0.0.1";
  const preferredTrackerPort = Number(trackerConfig?.trackerPort || process.env.TRACKER_PORT || 5000);

  return {
    trackerConfig,
    localIps,
    suggestedLanTrackerHost: localIps[0] || "127.0.0.1",
    preferredTrackerHost,
    preferredTrackerPort,
  };
}

function saveTrackerConfig(config = {}) {
  const trackerHost = String(config.trackerHost || "").trim() || "127.0.0.1";
  const trackerPort = Number(config.trackerPort || 5000);
  const bindHost = String(config.bindHost || "0.0.0.0").trim() || "0.0.0.0";

  if (!Number.isInteger(trackerPort) || trackerPort < 1 || trackerPort > 65535) {
    throw new Error("Porta do tracker invalida.");
  }

  const payload = {
    trackerHost,
    trackerPort,
    bindHost,
    updatedAt: new Date().toISOString(),
  };

  fs.writeFileSync(getTrackerConfigPath(), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  return payload;
}

function resolvePythonCommand() {
  const root = getProjectRoot();
  const candidates = process.platform === "win32"
    ? [
        path.join(root, ".venv", "Scripts", "python.exe"),
        path.join(root, "venv", "Scripts", "python.exe"),
        "python",
        "py",
      ]
    : [
        path.join(root, ".venv", "bin", "python"),
        path.join(root, "venv", "bin", "python"),
        "python3",
        "python",
      ];
  return candidates.find((candidate) => candidate === "python" || candidate === "python3" || candidate === "py" || fs.existsSync(candidate));
}

function startBackend() {
  if (backendProcess) {
    return;
  }

  const root = getProjectRoot();
  const python = resolvePythonCommand();
  if (!python) {
    throw new Error("Nenhum interpretador Python encontrado em .venv, venv ou PATH.");
  }

  backendExitedDuringStartup = false;
  backendStartupError = null;
  appendLog(`Starting Desktop API with '${python}' from '${root}'`);
  backendProcess = spawn(
    python,
    ["-m", "src.desktop_api.server"],
    {
      cwd: root,
      env: {
        ...process.env,
        DESKTOP_API_HOST: API_HOST,
        DESKTOP_API_PORT: API_PORT,
      },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    }
  );

  backendProcess.stdout?.on("data", (chunk) => {
    appendLog(`[desktop-api stdout] ${String(chunk).trimEnd()}`);
  });

  backendProcess.stderr?.on("data", (chunk) => {
    const text = String(chunk).trimEnd();
    backendStartupError = text || backendStartupError;
    appendLog(`[desktop-api stderr] ${text}`);
  });

  backendProcess.on("error", (error) => {
    backendStartupError = error.message;
    appendLog(`[desktop-api spawn error] ${error.stack || error.message}`);
  });

  backendProcess.on("exit", (code, signal) => {
    backendExitedDuringStartup = true;
    appendLog(`[desktop-api exit] code=${code} signal=${signal || "none"}`);
    backendProcess = null;
  });
}

function stopBackend() {
  if (!backendProcess) {
    return;
  }
  backendProcess.kill();
  backendProcess = null;
}

function waitForBackend(timeoutMs = 15000) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const tryConnect = () => {
      if (backendExitedDuringStartup) {
        reject(new Error(`Desktop API encerrou antes de responder. ${backendStartupError || `Veja o log em ${getLogFilePath()}`}`));
        return;
      }

      const request = http.get(`${API_BASE}/api/health`, (response) => {
        response.resume();
        resolve();
      });

      request.on("error", () => {
        if (Date.now() - startedAt > timeoutMs) {
          reject(new Error(`Desktop API nao iniciou a tempo. ${backendStartupError || `Veja o log em ${getLogFilePath()}`}`));
          return;
        }
        setTimeout(tryConnect, 300);
      });
    };

    tryConnect();
  });
}

async function createWindow() {
  startBackend();
  await waitForBackend();

  const win = new BrowserWindow({
    width: 1366,
    height: 768,
    minWidth: 1366,
    minHeight: 768,
    backgroundColor: "#09111a",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  await win.loadFile(path.join(__dirname, "index.html"));
}

ipcMain.handle("pick-iso-file", async () => {
  const result = await dialog.showOpenDialog({
    title: "Escolher ISO para compartilhar",
    properties: ["openFile"],
    filters: [
      { name: "Arquivos ISO", extensions: ["iso"] },
      { name: "Todos os arquivos", extensions: ["*"] },
    ],
  });

  if (result.canceled || !result.filePaths[0]) {
    return null;
  }
  return result.filePaths[0];
});

ipcMain.handle("pick-folder", async () => {
  const result = await dialog.showOpenDialog({
    title: "Escolher pasta",
    properties: ["openDirectory", "createDirectory"],
  });

  if (result.canceled || !result.filePaths[0]) {
    return null;
  }
  return result.filePaths[0];
});

ipcMain.handle("get-desktop-context", () => getDesktopContext());

ipcMain.handle("save-tracker-config", (_event, config) => saveTrackerConfig(config));

ipcMain.handle("copy-text", (_event, text) => {
  clipboard.writeText(String(text || ""));
  return true;
});

app.whenReady().then(async () => {
  try {
    await createWindow();
  } catch (error) {
    dialog.showErrorBox("Falha ao iniciar", String(error.message || error));
    app.quit();
  }
});

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  stopBackend();
});
