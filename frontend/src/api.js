async function request(url, options = {}) {
  const res = await fetch(url, options);
  const contentType = res.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const detail = isJson ? data?.detail || data?.error || JSON.stringify(data) : data;
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return data;
}

export const api = {
  getCapabilities: () => request('/api/capabilities'),
  getSamples: () => request('/api/samples'),
  listSessions: () => request('/api/sessions'),
  getSession: (id) => request(`/api/sessions/${encodeURIComponent(id)}`),
  deleteSession: (id) =>
    request(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  analyzeText: (payload) =>
    request('/api/sessions/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  uploadFile: (file, mode, enabledTypes) => {
    const form = new FormData();
    form.append('file', file);
    form.append('mode', mode);
    form.append('enabled_types', enabledTypes.join(','));
    return request('/api/sessions/upload', { method: 'POST', body: form });
  },

  updateSession: (id, payload) =>
    request(`/api/sessions/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  addManualEntity: (id, payload) =>
    request(`/api/sessions/${encodeURIComponent(id)}/entities`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  rerunSession: (id) =>
    request(`/api/sessions/${encodeURIComponent(id)}/rerun`, { method: 'POST' }),

  restoreText: (id, text, strict = true) =>
    request(`/api/sessions/${encodeURIComponent(id)}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, strict }),
    }),

  exportUrl: (id, kind = 'redacted') =>
    `/api/sessions/${encodeURIComponent(id)}/export?kind=${encodeURIComponent(kind)}`,
};
