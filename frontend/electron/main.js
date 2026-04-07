// frontend/electron/main.js
const { app, BrowserWindow, dialog } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const { spawn } = require("child_process");

let pythonProcess = null;
const API_HOST = "127.0.0.1";
const API_PORT = 8000;
const API_HEALTH_PATH = "/api/health";

function getProjectRoot() {
  if (app.isPackaged) {
    return process.resourcesPath;
  }
  return path.join(__dirname, "..", "..");
}

function getIndexHtmlPath() {
  if (app.isPackaged) {
    return path.join(__dirname, "src", "index.html");
  }
  return path.join(__dirname, "..", "src", "index.html");
}

function createWindow() {
  const mainWindow = new BrowserWindow({
    width: 1100,
    height: 700,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: false,
      sandbox: false,
      webSecurity: false,
      allowRunningInsecureContent: true
    }
  });

  const indexPath = getIndexHtmlPath();
  console.log("[MAIN] Carregando index.html em:", indexPath);
  mainWindow.loadFile(indexPath);
}

function findFirstExistingPath(paths) {
  for (const p of paths) {
    if (typeof p === "string" && p.toLowerCase() === "python") {
      return p;
    }
    if (fs.existsSync(p)) {
      return p;
    }
  }
  return null;
}

function getPythonCandidates(projectRoot) {
  return [
    path.join(projectRoot, ".venv313", "Scripts", "python.exe"),
    path.join(projectRoot, ".venv", "Scripts", "python.exe"),
    path.join(projectRoot, ".venv-client", "Scripts", "python.exe"),
    path.join(projectRoot, "..", ".venv-client", "Scripts", "python.exe"),
    "python"
  ];
}

function waitForApiReady(timeoutMs = 30000) {
  const startedAt = Date.now();

  return new Promise((resolve, reject) => {
    const tryHealth = () => {
      const req = http.get(
        {
          host: API_HOST,
          port: API_PORT,
          path: API_HEALTH_PATH,
          timeout: 1500
        },
        (res) => {
          res.resume();
          if (res.statusCode && res.statusCode < 500) {
            resolve();
            return;
          }
          retryOrFail();
        }
      );

      req.on("error", retryOrFail);
      req.on("timeout", () => {
        req.destroy();
        retryOrFail();
      });
    };

    const retryOrFail = () => {
      if (Date.now() - startedAt >= timeoutMs) {
        reject(new Error(`API nao respondeu em ${timeoutMs}ms`));
        return;
      }
      setTimeout(tryHealth, 400);
    };

    tryHealth();
  });
}

async function startPythonApi() {
  const projectRoot = getProjectRoot();
  const pythonExe = findFirstExistingPath(getPythonCandidates(projectRoot)) || "python";
  const serverPath = path.join(projectRoot, "api", "server.py");

  console.log("[MAIN] Iniciando API Python:");
  console.log("       projectRoot =", projectRoot);
  console.log("       pythonExe   =", pythonExe);
  console.log("       serverPath  =", serverPath);

  if (!fs.existsSync(serverPath)) {
    throw new Error(`Arquivo do servidor nao encontrado: ${serverPath}`);
  }

  pythonProcess = spawn(pythonExe, [serverPath], {
    cwd: projectRoot,
    shell: false,
    env: { ...process.env, PYTHONUNBUFFERED: "1" }
  });

  pythonProcess.stdout.on("data", (data) => {
    console.log(`[PY] ${data}`.trim());
  });

  pythonProcess.stderr.on("data", (data) => {
    console.error(`[PY-ERR] ${data}`.trim());
  });

  pythonProcess.on("close", (code) => {
    console.log(`[MAIN] Python server finalizado com codigo ${code}`);
  });

  await new Promise((resolve, reject) => {
    pythonProcess.once("spawn", resolve);
    pythonProcess.once("error", reject);
  });

  await waitForApiReady();
}

app.whenReady().then(async () => {
  try {
    await startPythonApi();
  } catch (err) {
    console.error("[MAIN] Falha ao iniciar backend:", err);
    dialog.showErrorBox(
      "Falha ao iniciar backend",
      `Nao foi possivel iniciar a API local.\n\n${err.message || String(err)}`
    );
  }

  createWindow();

  app.on("activate", function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", function () {
  if (process.platform !== "darwin") {
    if (pythonProcess) {
      pythonProcess.kill();
    }
    app.quit();
  }
});
