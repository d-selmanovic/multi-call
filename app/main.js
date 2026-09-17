const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");

// The app bundles no Python: it starts the demo backend (uv/uvicorn) from
// SONIOX_DEMO_HOME (default: /Applications/soniox-translate-demo) and opens
// the UI in a native window. If the backend is already running, it reuses it.

const PORT = Number(process.env.SONIOX_DEMO_PORT || 8000);
const DEMO_HOME = process.env.SONIOX_DEMO_HOME || "/Applications/soniox-translate-demo";
const HEALTH = `http://127.0.0.1:${PORT}/health`;
const UI = `http://localhost:${PORT}/?room=app`;

let backend = null;

function waitForServer(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const res = await fetch(url);
        if (res.ok) return resolve();
      } catch { /* not up yet */ }
      if (Date.now() > deadline) return reject(new Error(`Server nicht erreichbar: ${url}`));
      setTimeout(tick, 400);
    };
    tick();
  });
}

app.whenReady().then(async () => {
  try {
    await waitForServer(HEALTH, 1500);
    console.log("Backend läuft bereits – verwende es.");
  } catch {
    console.log(`Starte Backend in ${DEMO_HOME}…`);
    backend = spawn("uv", ["run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", String(PORT)], {
      cwd: DEMO_HOME,
      env: { ...process.env },
    });
    backend.stdout.on("data", (d) => console.log(`[backend] ${d}`));
    backend.stderr.on("data", (d) => console.error(`[backend] ${d}`));
    await waitForServer(HEALTH, 45000);
  }

  const win = new BrowserWindow({
    width: 1280,
    height: 860,
    title: "Live-Übersetzung Demo",
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true },
  });
  await win.loadURL(UI);

  app.on("window-all-closed", () => app.quit());
});

app.on("will-quit", () => {
  if (backend) backend.kill();
});
