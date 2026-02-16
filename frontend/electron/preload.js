// frontend/electron/preload.js
const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  // Adicione outras APIs seguras conforme necessário
});

// Mantenha o env também se estiver usando
contextBridge.exposeInMainWorld('env', {
  API_BASE_URL: 'http://127.0.0.1:8000',
  NODE_ENV: process.env.NODE_ENV || 'production'
});