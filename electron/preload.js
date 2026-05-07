const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktopBridge", {
  pickIsoFile: () => ipcRenderer.invoke("pick-iso-file"),
  pickFolder: () => ipcRenderer.invoke("pick-folder"),
  getDesktopContext: () => ipcRenderer.invoke("get-desktop-context"),
  copyText: (text) => ipcRenderer.invoke("copy-text", text),
});
