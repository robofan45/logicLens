// Used by Start-LogicLens.cmd to see whether LogicLens is already running on this PC.
//   node launcher-probe.mjs web   -> checks http://localhost:5173/
//   node launcher-probe.mjs api   -> checks http://127.0.0.1:8000/health
// Exit codes: 0 = LogicLens answers there, 1 = nothing is listening, 2 = another program has the port.

const what = process.argv[2] === "api" ? "api" : "web";
const url =
  process.env.LOGICLENS_PROBE_URL || // tests point this at a local server
  (what === "api" ? "http://127.0.0.1:8000/health" : "http://localhost:5173/");

function isLogicLens(body) {
  if (what === "web") return body.includes("LogicLens");
  try {
    const j = JSON.parse(body);
    return !!j && typeof j.status === "string" && typeof j.version === "string";
  } catch {
    return false;
  }
}

try {
  const res = await fetch(url, { signal: AbortSignal.timeout(3000), redirect: "manual" });
  process.exit(isLogicLens(await res.text()) ? 0 : 2);
} catch (e) {
  // Refused connection: free port. A timeout means something is listening but not answering.
  process.exit(e && e.name === "TimeoutError" ? 2 : 1);
}
