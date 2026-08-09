package com.idealagent

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.clickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.ClickableText
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.ArrowDropUp
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.AssistChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.OutlinedTextField
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.activity.compose.setContent
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { ChatScreen() }
    }
}

data class Message(val role: String, val text: String)

// ---- Провайдеры (с бесплатными опциями) ----
data class ProviderInfo(
    val key: String,
    val label: String,
    val models: List<String>,
    val signup: String?,
    val needsKey: Boolean,
)

val PROVIDERS = listOf(
    ProviderInfo(
        "openrouter", "OpenRouter — много бесплатных моделей",
        listOf("moonshotai/kimi-k3-free", "meta-llama/llama-3.1-8b-instruct:free", "google/gemma-2-9b-it:free", "deepseek/deepseek-r1-distill-llama-70b:free"),
        "https://openrouter.ai/keys", true,
    ),
    ProviderInfo(
        "groq", "Groq — очень быстро, бесплатно",
        listOf("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it", "llama3-70b-8192"),
        "https://console.groq.com/keys", true,
    ),
    ProviderInfo(
        "deepseek", "DeepSeek — бесплатно и недорого",
        listOf("deepseek-chat", "deepseek-reasoner"),
        "https://platform.deepseek.com/api_keys", true,
    ),
    ProviderInfo(
        "moonshot", "Moonshot AI / Kimi — бесплатные модели",
        listOf("kimi-k3-free", "kimi-k2-free", "moonshot-v1-8k"),
        "https://platform.moonshot.ai/", true,
    ),
    ProviderInfo(
        "together", "Together AI — открытые модели",
        listOf("meta-llama/Llama-3.3-70B-Instruct-Turbo", "mistralai/Mixtral-8x7B-Instruct-v0.1", "Qwen/Qwen2.5-72B-Instruct-Turbo"),
        "https://api.together.xyz/settings/api-keys", true,
    ),
    ProviderInfo(
        "gemini", "Google Gemini — бесплатный ключ",
        listOf("gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"),
        "https://aistudio.google.com/apikey", true,
    ),
    ProviderInfo(
        "openai", "OpenAI",
        listOf("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"),
        "https://platform.openai.com/api-keys", true,
    ),
    ProviderInfo(
        "anthropic", "Anthropic Claude",
        listOf("claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"),
        "https://console.anthropic.com/settings/keys", true,
    ),
    ProviderInfo(
        "ollama", "Ollama — локально, без ключа",
        listOf("llama3.1", "qwen2.5", "mistral", "deepseek-r1"),
        null, false,
    ),
)

// ---- Markdown парсер ----
sealed class MdBlock
data class CodeBlock(val lang: String, val code: String) : MdBlock()
data class Heading(val level: Int, val text: String) : MdBlock()
data class Paragraph(val lines: List<String>) : MdBlock()
data class BulletList(val items: List<String>) : MdBlock()
data class OrderedList(val items: List<String>) : MdBlock()
data class Quote(val text: String) : MdBlock()
object Hr : MdBlock()

private val RE_BLOCK = Regex("^\\s*(#{1,6}\\s+|>|[-*]\\s+|\\d+\\.\\s+|```|-{3,}|\\*{3,})")

fun parseMarkdown(src: String): List<MdBlock> {
    val lines = src.replace("\r\n", "\n").split("\n")
    val out = mutableListOf<MdBlock>()
    var i = 0
    while (i < lines.size) {
        val line = lines[i]
        when {
            line.startsWith("```") -> {
                val lang = line.removePrefix("```").trim()
                val buf = StringBuilder()
                i++
                while (i < lines.size && !lines[i].startsWith("```")) {
                    buf.appendLine(lines[i]); i++
                }
                i++ // закрывающий ```
                out.add(CodeBlock(lang, buf.toString().trimEnd('\n')))
            }
            line.matches(Regex("^#{1,6}\\s+.*")) -> {
                val lvl = line.takeWhile { it == '#' }.length
                out.add(Heading(lvl, line.drop(lvl).trim()))
                i++
            }
            line.startsWith(">") -> {
                val buf = StringBuilder()
                while (i < lines.size && lines[i].startsWith(">")) {
                    buf.appendLine(lines[i].removePrefix(">").trim()); i++
                }
                out.add(Quote(buf.toString().trimEnd('\n')))
            }
            line.matches(Regex("^\\s*[-*]\\s+.*")) -> {
                val items = mutableListOf<String>()
                while (i < lines.size && lines[i].matches(Regex("^\\s*[-*]\\s+.*"))) {
                    items.add(lines[i].replace(Regex("^\\s*[-*]\\s+"), "")); i++
                }
                out.add(BulletList(items))
            }
            line.matches(Regex("^\\s*\\d+\\.\\s+.*")) -> {
                val items = mutableListOf<String>()
                while (i < lines.size && lines[i].matches(Regex("^\\s*\\d+\\.\\s+.*"))) {
                    items.add(lines[i].replace(Regex("^\\s*\\d+\\.\\s+"), "")); i++
                }
                out.add(OrderedList(items))
            }
            line.isBlank() -> i++
            line.matches(Regex("^\\s*(-{3,}|\\*{3,})\\s*$")) -> { out.add(Hr); i++ }
            else -> {
                val buf = StringBuilder()
                while (i < lines.size && lines[i].isNotBlank() && !RE_BLOCK.matches(lines[i])) {
                    buf.appendLine(lines[i]); i++
                }
                out.add(Paragraph(buf.toString().trimEnd('\n').split("\n")))
            }
        }
    }
    return out
}

private val RE_INLINE = Regex("""(\*\*(.+?)\*\*)|(\*(.+?)\*)|(`(.+?)`)|(\[(.+?)\]\((.+?)\))""")

fun parseInline(text: String, linkColor: Color, codeBg: Color): AnnotatedString {
    val b = AnnotatedString.Builder()
    var last = 0
    for (m in RE_INLINE.findAll(text)) {
        if (m.range.first > last) b.append(text.substring(last, m.range.first))
        when {
            m.groups[2] != null -> {
                b.pushStyle(SpanStyle(fontWeight = FontWeight.Bold))
                b.append(m.groups[2]!!.value); b.pop()
            }
            m.groups[4] != null -> {
                b.pushStyle(SpanStyle(fontStyle = FontStyle.Italic))
                b.append(m.groups[4]!!.value); b.pop()
            }
            m.groups[6] != null -> {
                b.pushStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = codeBg))
                b.append(m.groups[6]!!.value); b.pop()
            }
            m.groups[8] != null -> {
                val start = b.length
                b.pushStyle(SpanStyle(color = linkColor, textDecoration = TextDecoration.Underline))
                b.append(m.groups[8]!!.value); b.pop()
                b.addStringAnnotation("url", m.groups[9]!!.value, start, b.length)
            }
        }
        last = m.range.last + 1
    }
    if (last < text.length) b.append(text.substring(last))
    return b.toAnnotatedString()
}

// ---- Утилиты ----
fun copyText(ctx: Context, text: String) {
    val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    cm.setPrimaryClip(ClipData.newPlainText("ideal-agent", text))
    Toast.makeText(ctx, "Скопировано в буфер", Toast.LENGTH_SHORT).show()
}

fun openUrl(ctx: Context, url: String) {
    try {
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Exception) {
        Toast.makeText(ctx, "Не удалось открыть ссылку", Toast.LENGTH_SHORT).show()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen() {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("ideal_agent", Context.MODE_PRIVATE) }
    var host by remember { mutableStateOf(prefs.getString("host", "192.168.2.107:8080") ?: "192.168.2.107:8080") }
    var provider by remember { mutableStateOf(prefs.getString("provider", "") ?: "") }
    var model by remember { mutableStateOf(prefs.getString("model", "") ?: "") }
    var apiKey by remember { mutableStateOf(prefs.getString("api_key", "") ?: "") }
    var prompt by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var settingsOpen by remember { mutableStateOf(false) }
    val messages = remember { mutableStateListOf<Message>() }
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()

    LaunchedEffect(host) { prefs.edit().putString("host", host).apply() }
    LaunchedEffect(provider) { prefs.edit().putString("provider", provider).apply() }
    LaunchedEffect(model) { prefs.edit().putString("model", model).apply() }
    LaunchedEffect(apiKey) { prefs.edit().putString("api_key", apiKey).apply() }

    fun send() {
        if (busy || prompt.isBlank()) return
        val h = host; val p = prompt; val pv = provider; val md = model; val key = apiKey
        prompt = ""
        messages.add(Message("user", p))
        busy = true
        scope.launch {
            val r = askAgent(h, p, pv, md, key)
            messages.add(Message("agent", r))
            busy = false
        }
    }

    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.scrollToItem(messages.lastIndex)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("ideal-agent") },
                actions = {
                    if (messages.isNotEmpty()) {
                        FilledIconButton(onClick = { messages.clear() }) {
                            Icon(Icons.Filled.Delete, contentDescription = "Очистить историю")
                        }
                    }
                    FilledIconButton(onClick = { settingsOpen = !settingsOpen }) {
                        Icon(Icons.Filled.Settings, contentDescription = "Настройки")
                    }
                },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .imePadding(),
        ) {
            AnimatedVisibility(
                visible = settingsOpen,
                enter = expandVertically() + fadeIn(),
                exit = shrinkVertically() + fadeOut(),
            ) {
                SettingsPanel(
                    host = host, onHost = { host = it },
                    provider = provider, onProvider = { provider = it },
                    model = model, onModel = { model = it },
                    apiKey = apiKey, onApiKey = { apiKey = it },
                )
            }

            if (messages.isEmpty()) {
                Box(
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "Отправьте сообщение агенту",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(top = 12.dp, bottom = 12.dp),
                ) {
                    items(messages) { msg ->
                        MessageRow(msg) { copyText(context, it) }
                    }
                    if (busy) {
                        item {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
                                Surface(
                                    color = MaterialTheme.colorScheme.surfaceVariant,
                                    shape = RoundedCornerShape(16.dp),
                                ) {
                                    CircularProgressIndicator(
                                        strokeWidth = 2.dp,
                                        modifier = Modifier.padding(14.dp).size(18.dp),
                                    )
                                }
                            }
                        }
                    }
                }
            }

            Surface(
                tonalElevation = 3.dp,
                shape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .navigationBarsPadding()
                    .padding(start = 10.dp, end = 10.dp, bottom = 14.dp),
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.Bottom,
                ) {
                    OutlinedTextField(
                        value = prompt,
                        onValueChange = { prompt = it },
                        label = { Text("Сообщение агенту") },
                        singleLine = false,
                        minLines = 1,
                        maxLines = 4,
                        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                            imeAction = androidx.compose.ui.text.input.ImeAction.Send,
                        ),
                        keyboardActions = androidx.compose.foundation.text.KeyboardActions(onSend = { send() }),
                        modifier = Modifier.weight(1f).padding(end = 8.dp),
                    )
                    FilledIconButton(
                        onClick = { send() },
                        enabled = !busy && prompt.isNotBlank(),
                        modifier = Modifier.size(48.dp),
                    ) {
                        if (busy) {
                            CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(22.dp))
                        } else {
                            Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Отправить")
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun MessageRow(msg: Message, onCopy: (String) -> Unit) {
    val isUser = msg.role == "user"
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Column(horizontalAlignment = if (isUser) Alignment.End else Alignment.Start) {
            Surface(
                color = if (isUser) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant,
                shape = RoundedCornerShape(16.dp),
                modifier = Modifier
                    .widthIn(max = 340.dp)
                    .combinedClickable(
                        onClick = {},
                        onLongClick = { onCopy(msg.text) },
                    ),
            ) {
                if (isUser) {
                    Text(msg.text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(12.dp))
                } else {
                    MarkdownView(msg.text) { onCopy(it) }
                }
            }
            if (!isUser) {
                FilledTonalIconButton(
                    onClick = { onCopy(msg.text) },
                    modifier = Modifier.size(26.dp).padding(top = 2.dp),
                ) {
                    Icon(Icons.Filled.ContentCopy, contentDescription = "Копировать сообщение", modifier = Modifier.size(14.dp))
                }
            }
        }
    }
}

@Composable
fun MarkdownView(text: String, onCopyCode: (String) -> Unit) {
    val blocks = remember(text) { parseMarkdown(text) }
    val linkColor = MaterialTheme.colorScheme.primary
    val codeBg = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
    Column(verticalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(12.dp)) {
        for (blk in blocks) {
            when (blk) {
                is CodeBlock -> CodeCard(blk.lang, blk.code) { onCopyCode(blk.code) }
                is Heading -> {
                    val style = when (blk.level) {
                        1 -> MaterialTheme.typography.titleLarge
                        2 -> MaterialTheme.typography.titleMedium
                        3 -> MaterialTheme.typography.titleSmall
                        else -> MaterialTheme.typography.bodyLarge
                    }
                    InlineText(blk.text, style.copy(fontWeight = FontWeight.Bold), linkColor, codeBg)
                }
                is Paragraph -> blk.lines.forEach { line ->
                    if (line.isBlank()) androidx.compose.foundation.layout.Spacer(Modifier.size(2.dp))
                    else InlineText(line, MaterialTheme.typography.bodyLarge, linkColor, codeBg)
                }
                is BulletList -> blk.items.forEach { item ->
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
                        Text("•", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(end = 8.dp))
                        InlineText(item, MaterialTheme.typography.bodyLarge, linkColor, codeBg, Modifier.weight(1f))
                    }
                }
                is OrderedList -> blk.items.forEachIndexed { idx, item ->
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
                        Text("${idx + 1}.", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(end = 8.dp))
                        InlineText(item, MaterialTheme.typography.bodyLarge, linkColor, codeBg, Modifier.weight(1f))
                    }
                }
                is Quote -> Surface(
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    InlineText(
                        blk.text,
                        MaterialTheme.typography.bodyMedium.copy(fontStyle = FontStyle.Italic),
                        linkColor, codeBg,
                        Modifier.padding(10.dp),
                    )
                }
                is Hr -> HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
            }
        }
    }
}

@Composable
fun InlineText(text: String, baseStyle: TextStyle, linkColor: Color, codeBg: Color, modifier: Modifier = Modifier) {
    val annotated = remember(text) { parseInline(text, linkColor, codeBg) }
    val ctx = LocalContext.current
    ClickableText(
        text = annotated,
        style = baseStyle,
        modifier = modifier,
        onClick = { offset ->
            annotated.getStringAnnotations("url", offset, offset).firstOrNull()?.let { openUrl(ctx, it.item) }
        },
    )
}

@Composable
fun CodeCard(lang: String, code: String, onCopy: () -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    lang.ifBlank { "code" },
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 10.dp, top = 6.dp, bottom = 2.dp),
                )
                IconButton(onClick = onCopy, modifier = Modifier.size(28.dp)) {
                    Icon(Icons.Filled.ContentCopy, contentDescription = "Копировать код", modifier = Modifier.size(15.dp))
                }
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f))
            SelectionContainer {
                Text(
                    code,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(10.dp)
                        .horizontalScroll(rememberScrollState()),
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsPanel(
    host: String, onHost: (String) -> Unit,
    provider: String, onProvider: (String) -> Unit,
    model: String, onModel: (String) -> Unit,
    apiKey: String, onApiKey: (String) -> Unit,
) {
    val ctx = LocalContext.current
    val sel = PROVIDERS.firstOrNull { it.key == provider }
    var expanded by remember { mutableStateOf(false) }
    var showKey by remember { mutableStateOf(false) }

    OutlinedCard(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(max = 360.dp)
            .padding(horizontal = 16.dp, vertical = 8.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp).verticalScroll(rememberScrollState())) {
            Text("Подключение", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = host, onValueChange = onHost,
                label = { Text("Хост:порт агента") },
                singleLine = true, modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
            Text(
                "Локальный адрес HTTP-канала, напр. 192.168.2.107:8080",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )

            androidx.compose.foundation.layout.Spacer(Modifier.size(12.dp))
            Text("LLM провайдер", style = MaterialTheme.typography.titleMedium)

            Box(
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            ) {
                OutlinedTextField(
                    value = sel?.label ?: "— выбери провайдера —",
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("Провайдер") },
                    trailingIcon = {
                        IconButton(onClick = { expanded = !expanded }) {
                            Icon(
                                if (expanded) Icons.Filled.ArrowDropUp else Icons.Filled.ArrowDropDown,
                                contentDescription = "Выбрать провайдера",
                            )
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
                DropdownMenu(
                    expanded = expanded,
                    onDismissRequest = { expanded = false },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    PROVIDERS.forEach { p ->
                        DropdownMenuItem(
                            text = { Text(p.label) },
                            onClick = {
                                onProvider(p.key)
                                if (model.isBlank() || sel == null) onModel(p.models.first())
                                else if (!p.models.contains(model)) onModel(p.models.first())
                                expanded = false
                            },
                        )
                    }
                }
            }

            OutlinedTextField(
                value = model, onValueChange = onModel,
                label = { Text("Модель") },
                singleLine = true,
                placeholder = { Text(sel?.models?.first() ?: "напр. gpt-4o-mini") },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )

            if (sel != null) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    sel.models.take(4).forEach { m ->
                        AssistChip(
                            onClick = { onModel(m) },
                            label = { Text(m, style = MaterialTheme.typography.labelSmall) },
                        )
                    }
                }
            }

            OutlinedTextField(
                value = apiKey, onValueChange = onApiKey,
                label = { Text("API-токен / ключ") },
                singleLine = true,
                enabled = sel?.needsKey != false,
                visualTransformation = if (showKey) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = {
                    if (sel?.needsKey != false) {
                        IconButton(onClick = { showKey = !showKey }) {
                            Icon(
                                if (showKey) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                                contentDescription = if (showKey) "Скрыть" else "Показать",
                            )
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )

            if (sel?.signup != null) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { openUrl(ctx, sel.signup) }
                        .padding(top = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        Icons.Filled.Link,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(16.dp),
                    )
                    Text(
                        " Получить ключ / регистрация",
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(start = 6.dp),
                    )
                }
            }
            if (sel?.needsKey == false) {
                Text(
                    "Ключ не требуется",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
        }
    }
}

suspend fun askAgent(host: String, prompt: String, provider: String, model: String, apiKey: String): String {
    return withContext(Dispatchers.IO) {
        try {
            val url = URL("http://$host/message")
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.connectTimeout = 120_000
            conn.readTimeout = 120_000
            val obj = JSONObject()
            obj.put("text", prompt)
            if (provider.isNotBlank()) obj.put("provider", provider)
            if (model.isNotBlank()) obj.put("model", model)
            if (apiKey.isNotBlank()) obj.put("api_key", apiKey)
            conn.outputStream.write(obj.toString().toByteArray())
            val code = conn.responseCode
            if (code == 200) {
                val txt = conn.inputStream.bufferedReader().readText()
                JSONObject(txt).optString("reply", txt)
            } else {
                "HTTP $code"
            }
        } catch (e: Exception) {
            "ошибка: ${e.message}"
        }
    }
}
