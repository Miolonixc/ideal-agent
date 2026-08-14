/** Experimental OpenTUI client for ideal-agent's local HTTP API.
 *
 * It contains no LLM credentials. The Python server remains the only process
 * that holds configuration, tools, MCP connections and safety policy.
 */
import {
  Box,
  InputRenderable,
  ScrollBoxRenderable,
  TextRenderable,
  createCliRenderer,
} from "@opentui/core"

type Config = { baseUrl: string; token: string; sessionId: string }

function option(name: string, fallback: string): string {
  const index = process.argv.indexOf(name)
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback
}

const config: Config = {
  baseUrl: option("--url", process.env.IDEAL_AGENT_URL ?? "http://127.0.0.1:8080").replace(/\/$/, ""),
  token: option("--token", process.env.IDEAL_HTTP_TOKEN ?? ""),
  sessionId: option("--session", process.env.IDEAL_SESSION_ID ?? "opentui"),
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers)
  if (config.token) headers.set("X-Ideal-Agent-Token", config.token)
  return fetch(`${config.baseUrl}${path}`, { ...init, headers })
}

const renderer = await createCliRenderer({ exitOnCtrlC: true })
const root = Box({
  width: "100%", height: "100%", flexDirection: "column", padding: 1,
  backgroundColor: "#101318",
})
const title = new TextRenderable(renderer, {
  id: "title", content: "⚡ ideal-agent · OpenTUI (experimental)", fg: "#6ee7ff",
})
const status = new TextRenderable(renderer, {
  id: "status", content: `server: ${config.baseUrl} · connecting…`, fg: "#9ca3af",
})
const transcript = new TextRenderable(renderer, {
  id: "transcript", content: "", fg: "#f3f4f6",
})
const transcriptPane = new ScrollBoxRenderable(renderer, {
  id: "transcript-pane", flexGrow: 1, width: "100%", scrollY: true,
  stickyScroll: true, stickyStart: "bottom", border: true, borderStyle: "rounded",
  borderColor: "#374151", paddingX: 1, paddingY: 0,
})
let input: InputRenderable
input = new InputRenderable(renderer, {
  id: "prompt", width: "100%", placeholder: "Сообщение агенту — Enter отправить · Ctrl+C выход",
  backgroundColor: "#1f2937", focusedBackgroundColor: "#273449",
  textColor: "#ffffff", cursorColor: "#6ee7ff", maxLength: 20_000,
  onSubmit: () => void send(input.value),
})

root.add(title)
root.add(status)
root.add(Box({ height: 1 }))
transcriptPane.add(transcript)
root.add(transcriptPane)
root.add(Box({ height: 1 }))
root.add(input)
renderer.root.add(root)

let lines: string[] = []
let busy = false
function redraw() {
  // Keep the in-memory transcript bounded; OpenTUI handles terminal wrapping.
  transcript.content = lines.slice(-120).join("\n\n")
}
function add(role: "you" | "agent" | "system", text: string) {
  const prefix = role === "you" ? "you>" : role === "agent" ? "agent>" : "system>"
  lines.push(`${prefix} ${text}`)
  redraw()
}
function setStatus(text: string, color = "#9ca3af") {
  status.content = text
  status.fg = color
}

async function checkServer() {
  try {
    const response = await request("/status")
    if (!response.ok) throw new Error(response.status === 401 ? "неверный HTTP-токен" : `HTTP ${response.status}`)
    const data = await response.json() as { provider?: string; model?: string; mode?: string; tools?: number }
    setStatus(`online · ${data.provider ?? "agent"}/${data.model ?? "?"} · ${data.mode ?? "?"}`, "#86efac")
    return data
  } catch (error) {
    setStatus(`offline · ${error instanceof Error ? error.message : String(error)}`, "#fca5a5")
    add("system", "Запусти агент: python3 main.py http --port 8080. Curses TUI остаётся доступен: python3 main.py tui")
  }
}

async function showServerInfo() {
  const data = await checkServer()
  if (data) add("system", `Подключено · tools: ${data.tools ?? 0} · F3: список skills/tools · Ctrl+L: очистить историю`)
}

async function send(text: string) {
  if (!text.trim() || busy) return
  busy = true
  add("you", text)
  input.value = ""
  setStatus("agent отвечает…", "#fde68a")
  let answer = ""
  add("agent", "")
  try {
    const response = await request("/message/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, session_id: config.sessionId }),
    })
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    while (true) {
      const part = await reader.read()
      if (part.done) break
      buffer += decoder.decode(part.value, { stream: true })
      const events = buffer.split("\n\n")
      buffer = events.pop() ?? ""
      for (const event of events) {
        const data = event.split("\n").find((line) => line.startsWith("data: "))?.slice(6)
        if (!data || data === "[DONE]") continue
        const message = JSON.parse(data) as { chunk?: string }
        answer += message.chunk ?? ""
        lines[lines.length - 1] = `agent> ${answer}`
        redraw()
      }
    }
    setStatus("online", "#86efac")
  } catch (error) {
    lines[lines.length - 1] = `agent> [ошибка] ${error instanceof Error ? error.message : String(error)}`
    redraw()
    setStatus("ошибка подключения", "#fca5a5")
  } finally {
    busy = false
    input.focus()
  }
}

input.focus()
renderer.keyInput.on("keypress", (key) => {
  if (busy) return
  if (key.name === "f2") void showServerInfo()
  if (key.name === "f3") void send("/skills")
  if (key.ctrl && key.name === "l") {
    lines = []
    redraw()
    add("system", "История OpenTUI очищена")
  }
})
await showServerInfo()
