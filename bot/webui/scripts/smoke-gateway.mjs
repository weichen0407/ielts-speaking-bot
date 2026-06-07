const base = process.env.WEBUI_BASE || "http://127.0.0.1:5173";
const secret = process.env.NANOBOT_SECRET || "";

async function requestJson(path, init = {}) {
  const response = await fetch(`${base}${path}`, init);
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    throw new Error(`${path} failed with HTTP ${response.status}`);
  }
  if (!contentType.toLowerCase().includes("application/json")) {
    const text = await response.text();
    throw new Error(`${path} returned non-JSON content: ${text.slice(0, 80)}`);
  }
  return response.json();
}

const headers = secret ? { "X-Nanobot-Auth": secret } : {};
const bootstrap = await requestJson("/webui/bootstrap", { headers });
if (!bootstrap.token || !bootstrap.ws_path) {
  throw new Error("bootstrap response missing token or ws_path");
}

const auth = { Authorization: `Bearer ${bootstrap.token}` };
const graph = await requestJson("/api/wiki/graph", { headers: auth });
if (!Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
  throw new Error("wiki graph response must contain nodes and edges arrays");
}

const monitor = await requestJson("/api/admin/monitor", { headers: auth });
if (!Array.isArray(monitor.triggers) || !Array.isArray(monitor.expected_triggers)) {
  throw new Error("admin monitor response missing trigger arrays");
}

console.log(JSON.stringify({
  ok: true,
  base,
  graph_nodes: graph.nodes.length,
  graph_edges: graph.edges.length,
  triggers: monitor.triggers.length,
}, null, 2));
