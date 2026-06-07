const SHEET_NAME = 'suscriptores';

function jsonResponse(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

function getSheet() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(SHEET_NAME);
  }
  const headers = ['chat_id', 'nombre', 'estacion', 'nivel_minimo', 'activo', 'registrado', 'actualizado'];
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(headers);
  }
  return sheet;
}

function authorize_(apiKey) {
  const expected = PropertiesService.getScriptProperties().getProperty('SUBSCRIBERS_API_KEY');
  return expected && apiKey && apiKey === expected;
}

function listSubscribers_() {
  const sheet = getSheet();
  const values = sheet.getDataRange().getValues();
  if (values.length <= 1) {
    return [];
  }
  return values.slice(1)
    .filter(row => String(row[0] || '').trim())
    .map(row => ({
      chat_id: String(row[0] || '').trim(),
      nombre: String(row[1] || 'Suscriptor').trim(),
      estacion: String(row[2] || 'Todas').trim(),
      nivel_minimo: String(row[3] || 'AMARILLO').trim(),
      activo: String(row[4]).toLowerCase() !== 'false',
      registrado: String(row[5] || ''),
      actualizado: String(row[6] || ''),
    }));
}

function upsertSubscriber_(subscriber) {
  const sheet = getSheet();
  const chatId = String(subscriber.chat_id || '').trim();
  if (!/^\d+$/.test(chatId)) {
    throw new Error('chat_id invalido');
  }

  const now = new Date().toISOString();
  const nombre = String(subscriber.nombre || 'Suscriptor').trim();
  const estacion = String(subscriber.estacion || 'Todas').trim();
  const nivel = String(subscriber.nivel_minimo || 'AMARILLO').trim();
  const activo = subscriber.activo !== false;
  const registrado = String(subscriber.registrado || now);
  const row = [chatId, nombre, estacion, nivel, activo, registrado, now];

  const values = sheet.getDataRange().getValues();
  for (let i = 1; i < values.length; i++) {
    if (String(values[i][0]).trim() === chatId) {
      sheet.getRange(i + 1, 1, 1, row.length).setValues([row]);
      return { updated: true };
    }
  }

  sheet.appendRow(row);
  return { created: true };
}

function handleRequest_(payload) {
  if (!authorize_(payload.api_key)) {
    return { ok: false, error: 'No autorizado' };
  }

  if (payload.action === 'list') {
    return { ok: true, subscribers: listSubscribers_() };
  }

  if (payload.action === 'upsert') {
    return { ok: true, result: upsertSubscriber_(payload.subscriber || {}) };
  }

  return { ok: false, error: 'Accion no soportada' };
}

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents || '{}');
    return jsonResponse(handleRequest_(payload));
  } catch (err) {
    return jsonResponse({ ok: false, error: String(err.message || err) });
  }
}

function doGet() {
  return jsonResponse({
    ok: true,
    service: 'NAZCA Telegram Subscribers',
    usage: 'Use POST with api_key and action.',
  });
}
