// frontend/electron/main.js
const { app, BrowserWindow } = require("electron");
const path = require("path");
const { spawn } = require("child_process");

let pythonProcess = null;

// Descobre o "root" do projeto Python dependendo se está em dev ou buildado
function getProjectRoot() {
  if (app.isPackaged) {
    // Dentro do build (EXE): tudo que colocamos em extraResources
    // vai para process.resourcesPath
    return process.resourcesPath;
  }

  // Dev: rodando em C:\...\1ARBIT\frontend\electron
  // subimos 2 níveis para voltar ao 1ARBIT
  return path.join(__dirname, "..", "..");
}

// Caminho correto do index.html em dev x build
function getIndexHtmlPath() {
  if (app.isPackaged) {
    // Dentro do app.asar -> main.js e src/index.html são "irmãos"
    return path.join(__dirname, "src", "index.html");
  }
  // Dev: index.html fica em ..\src\index.html
  return path.join(__dirname, "..", "src", "index.html");
}

function createWindow() {
  const mainWindow = new BrowserWindow({
    width: 1100,
    height: 700,
    webPreferences: {
      // NÃO vamos usar preload, então removemos para evitar erro
      // preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: false, // não usamos contextBridge
      sandbox: false,
      webSecurity: false, // para poder carregar file:// + esm.sh
      allowRunningInsecureContent: true
    }
  });

  const indexPath = getIndexHtmlPath();
  console.log("[MAIN] Carregando index.html em:", indexPath);

  mainWindow.loadFile(indexPath);

  // Descomenta se quiser ver o DevTools
  // mainWindow.webContents.openDevTools();
}

function startPythonApi() {
  const projectRoot = getProjectRoot();

  // Caminho do Python da venv: .venv313\Scripts\python.exe
  const pythonExe = path.join(projectRoot, ".venv313", "Scripts", "python.exe");

  // Caminho do server.py: api\server.py
  const serverPath = path.join(projectRoot, "api", "server.py");

  console.log("[MAIN] Iniciando API Python:");
  console.log("       projectRoot =", projectRoot);
  console.log("       pythonExe   =", pythonExe);
  console.log("       serverPath  =", serverPath);

  pythonProcess = spawn(pythonExe, [serverPath], {
    cwd: projectRoot,
    shell: false
  });

  pythonProcess.stdout.on("data", (data) => {
    console.log(`[PY] ${data}`.trim());
  });

  pythonProcess.stderr.on("data", (data) => {
    console.error(`[PY-ERR] ${data}`.trim());
  });

  pythonProcess.on("close", (code) => {
    console.log(`[MAIN] Python server finalizado com código ${code}`);
  });
}

app.whenReady().then(() => {
  startPythonApi();
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
