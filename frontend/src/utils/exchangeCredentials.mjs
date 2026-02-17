export function buildRotatePayload(form) {
  const payload = {
    label: form.label,
    status: form.status
  };
  if ((form.apiKey || "").trim()) payload.apiKey = form.apiKey.trim();
  if ((form.apiSecret || "").trim()) payload.apiSecret = form.apiSecret.trim();
  if ((form.passphrase || "").trim()) payload.passphrase = form.passphrase.trim();
  return payload;
}

export function canManageCredentials(rolesRaw) {
  const set = new Set(String(rolesRaw || "").split(",").map((x) => x.trim().toUpperCase()));
  return set.has("ADMIN");
}
