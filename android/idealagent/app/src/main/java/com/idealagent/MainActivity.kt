package com.idealagent

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.PixelFormat
import android.media.ImageReader
import android.media.projection.MediaProjectionManager
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.provider.OpenableColumns
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.util.Base64
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import android.app.Activity
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.clickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.Image
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
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.filled.VolumeOff
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.ArrowDropUp
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
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
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
import androidx.compose.ui.graphics.asImageBitmap
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
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.util.Locale
import java.util.UUID

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { ChatScreen() }
    }
}

data class Message(val role: String, val text: String)

data class Attachment(val name: String, val mime: String, val bytes: ByteArray)

private const val MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024

data class Session(val id: String, var name: String, val messages: MutableList<Message>)

/** Cancels the underlying HTTP read as well as the coroutine consuming it. */
class StreamCancellation {
    @Volatile private var connection: HttpURLConnection? = null

    fun attach(value: HttpURLConnection) { connection = value }
    fun clear(value: HttpURLConnection) { if (connection === value) connection = null }
    fun cancel() { connection?.disconnect() }
}

// ---- Markdown парсер ----
sealed class MdBlock
data class CodeBlock(val lang: String, val code: String) : MdBlock()
data class Heading(val level: Int, val text: String) : MdBlock()
data class Paragraph(val lines: List<String>) : MdBlock()
data class BulletList(val items: List<String>) : MdBlock()
data class OrderedList(val items: List<String>) : MdBlock()
data class Quote(val text: String) : MdBlock()
data class ImageBlock(val alt: String, val url: String) : MdBlock()
object Hr : MdBlock()

private val RE_BLOCK = Regex("^\\s*(#{1,6}\\s+|>|[-*]\\s+|\\d+\\.\\s+|```|-{3,}|\\*{3,})")
private val RE_IMG = Regex("^!\\[(.*?)\\]\\((.+?)\\)$")

fun parseMarkdown(src: String): List<MdBlock> {
    val lines = src.replace("\r\n", "\n").split("\n")
    val out = mutableListOf<MdBlock>()
    var i = 0
    while (i < lines.size) {
        val line = lines[i]
        val img = RE_IMG.matchEntire(line)
        if (img != null) {
            out.add(ImageBlock(img.groupValues[1], img.groupValues[2]))
            i++
            continue
        }
        when {
            line.startsWith("```") -> {
                val lang = line.removePrefix("```").trim()
                val buf = StringBuilder()
                i++
                while (i < lines.size && !lines[i].startsWith("```")) {
                    buf.appendLine(lines[i]); i++
                }
                i++
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

fun readLimited(input: InputStream, limit: Int = MAX_ATTACHMENT_BYTES): ByteArray? {
    val out = ByteArrayOutputStream()
    val buffer = ByteArray(16 * 1024)
    while (true) {
        val count = input.read(buffer)
        if (count < 0) break
        if (out.size() + count > limit) return null
        out.write(buffer, 0, count)
    }
    return out.toByteArray()
}

fun uriToAttachment(ctx: Context, uri: Uri): Attachment? {
    return try {
        val mime = ctx.contentResolver.getType(uri) ?: "application/octet-stream"
        val name = try {
            ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
                val i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (i >= 0 && c.moveToFirst()) c.getString(i) else null
            }
        } catch (_: Exception) { null } ?: "file"
        val bytes = if (mime.startsWith("image/")) {
            val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            ctx.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) }
            val scale = (maxOf(opts.outWidth, opts.outHeight, 1) / 1600f).coerceAtLeast(1f)
            val opts2 = BitmapFactory.Options().apply { inSampleSize = scale.toInt().coerceAtLeast(1) }
            val bmp = ctx.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts2) } ?: return null
            val out = ByteArrayOutputStream()
            bmp.compress(Bitmap.CompressFormat.JPEG, 80, out)
            out.toByteArray()
        } else {
            ctx.contentResolver.openInputStream(uri)?.use { readLimited(it) } ?: return null
        }
        if (bytes.size > MAX_ATTACHMENT_BYTES) return null
        Attachment(name, mime, bytes)
    } catch (_: Exception) { null }
}

fun captureScreen(ctx: Context, data: Intent, onCaptured: (Attachment) -> Unit) {
    try {
        val mgr = ctx.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val projection = mgr.getMediaProjection(Activity.RESULT_OK, data)
        val metrics = ctx.resources.displayMetrics
        val w = metrics.widthPixels
        val h = metrics.heightPixels
        val dpi = metrics.densityDpi
        val reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 1)
        val display = projection.createVirtualDisplay(
            "capture", w, h, dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader.surface, null, null,
        )
        val thread = HandlerThread("screen-capture").also { it.start() }
        Handler(thread.looper).postDelayed({
            try {
                val image = reader.acquireLatestImage()
                var bmp: Bitmap? = null
                if (image != null) {
                    val plane = image.planes[0]
                    val buffer = plane.buffer
                    val rowPadding = plane.rowStride - plane.pixelStride * w
                    val clean = Bitmap.createBitmap(w + rowPadding / plane.pixelStride, h, Bitmap.Config.ARGB_8888)
                    clean.copyPixelsFromBuffer(buffer)
                    image.close()
                    bmp = if (rowPadding == 0) clean else Bitmap.createBitmap(clean, 0, 0, w, h)
                }
                val out = ByteArrayOutputStream()
                bmp?.compress(Bitmap.CompressFormat.JPEG, 85, out)
                val bytes = out.toByteArray()
                Handler(Looper.getMainLooper()).post {
                    onCaptured(Attachment("screenshot_${System.currentTimeMillis()}.jpg", "image/jpeg", bytes))
                }
            } catch (_: Exception) {
            } finally {
                try { display.release() } catch (_: Exception) { }
                try { projection.stop() } catch (_: Exception) { }
                try { reader.close() } catch (_: Exception) { }
                thread.quitSafely()
            }
        }, 350)
    } catch (_: Exception) { }
}

object KeyStoreCrypto {
    private const val ALIAS = "ideal_agent_ks"
    private const val ANDROID_KEYSTORE = "AndroidKeyStore"
    private const val TRANSFORM = "AES/GCM/NoPadding"

    private fun secretKey(): SecretKey {
        val ks = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        if (ks.containsAlias(ALIAS)) return ks.getKey(ALIAS, null) as SecretKey
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        val spec = KeyGenParameterSpec.Builder(
            ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .build()
        gen.init(spec)
        return gen.generateKey()
    }

    fun encrypt(plain: String): String {
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val iv = cipher.iv
        val enc = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        val out = ByteArray(iv.size + enc.size)
        System.arraycopy(iv, 0, out, 0, iv.size)
        System.arraycopy(enc, 0, out, iv.size, enc.size)
        return Base64.encodeToString(out, Base64.NO_WRAP)
    }

    fun decrypt(cipherText: String): String {
        val data = Base64.decode(cipherText, Base64.NO_WRAP)
        val iv = data.copyOfRange(0, 12)
        val enc = data.copyOfRange(12, data.size)
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(128, iv))
        return String(cipher.doFinal(enc), Charsets.UTF_8)
    }
}

fun loadSecret(prefs: SharedPreferences, name: String): String {
    val enc = prefs.getString(name, "") ?: ""
    if (enc.isBlank()) return ""
    return runCatching { KeyStoreCrypto.decrypt(enc) }.getOrDefault("")
}

fun saveSecret(prefs: SharedPreferences, name: String, value: String) {
    if (value.isBlank()) prefs.edit().remove(name).apply()
    else prefs.edit().putString(name, KeyStoreCrypto.encrypt(value)).apply()
}

/** Обычный HTTP допускается только к агенту на этом устройстве. */
fun agentBaseUrl(host: String): String {
    val entered = host.trim().removeSuffix("/")
    require(entered.isNotBlank()) { "Укажите хост и порт агента" }
    val raw = if ("://" in entered) entered else "http://$entered"
    val uri = URI(raw)
    val scheme = uri.scheme?.lowercase() ?: throw IllegalArgumentException("Некорректный адрес")
    val address = uri.host ?: throw IllegalArgumentException("Некорректный хост")
    require(uri.userInfo == null && uri.query == null && uri.fragment == null && (uri.path == null || uri.path.isEmpty())) {
        "Укажите только хост:порт без пути"
    }
    require(scheme == "http" || scheme == "https") { "Допустимы только HTTP или HTTPS" }
    val local = address.equals("localhost", ignoreCase = true) || address == "127.0.0.1" || address == "::1"
    require(scheme == "https" || local) { "Для удалённого агента используйте HTTPS" }
    return "$scheme://${uri.rawAuthority}"
}

fun loadSessions(ctx: Context): List<Session> {
    return try {
        val f = File(ctx.filesDir, "sessions.json")
        if (!f.exists()) return emptyList()
        val arr = JSONArray(f.readText())
        val out = mutableListOf<Session>()
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            val msgs = mutableListOf<Message>()
            val ma = o.getJSONArray("messages")
            for (j in 0 until ma.length()) {
                val m = ma.getJSONObject(j)
                msgs.add(Message(m.getString("role"), m.getString("text")))
            }
            out.add(Session(o.getString("id"), o.optString("name", "Чат"), msgs))
        }
        out
    } catch (_: Exception) { emptyList() }
}

fun saveSessions(ctx: Context, list: List<Session>) {
    try {
        val arr = JSONArray()
        for (s in list) {
            val o = JSONObject()
            o.put("id", s.id)
            o.put("name", s.name)
            val ma = JSONArray()
            for (m in s.messages) {
                val mo = JSONObject()
                mo.put("role", m.role)
                mo.put("text", m.text)
                ma.put(mo)
            }
            o.put("messages", ma)
            arr.put(o)
        }
        File(ctx.filesDir, "sessions.json").writeText(arr.toString())
    } catch (_: Exception) { }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen() {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("ideal_agent", Context.MODE_PRIVATE) }
    var host by remember { mutableStateOf(prefs.getString("host", "127.0.0.1:8080") ?: "127.0.0.1:8080") }
    var accessToken by remember { mutableStateOf(loadSecret(prefs, "http_token_enc")) }
    var prompt by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var requestJob by remember { mutableStateOf<Job?>(null) }
    var streamCancellation by remember { mutableStateOf<StreamCancellation?>(null) }
    var settingsOpen by remember { mutableStateOf(false) }
    val attachments = remember { mutableStateListOf<Attachment>() }
    var attachMenu by remember { mutableStateOf(false) }
    var sessionsMenu by remember { mutableStateOf(false) }
    var ttsOn by remember { mutableStateOf(false) }
    var recording by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    val sessions = remember {
        mutableStateListOf<Session>().apply {
            val loaded = loadSessions(context)
            if (loaded.isEmpty()) add(Session(UUID.randomUUID().toString(), "Чат 1", mutableListOf()))
            else addAll(loaded)
        }
    }
    var currentId by remember { mutableStateOf(sessions.first().id) }
    val messages = remember { mutableStateListOf<Message>() }
    LaunchedEffect(currentId) {
        messages.clear()
        messages.addAll(sessions.first { it.id == currentId }.messages)
    }

    val pickLauncher = rememberLauncherForActivityResult(ActivityResultContracts.GetMultipleContents()) { uris ->
        uris.forEach { uri -> uriToAttachment(context, uri)?.let { attachments.add(it) } }
    }
    val camLauncher = rememberLauncherForActivityResult(ActivityResultContracts.TakePicturePreview()) { bmp ->
        bmp?.let {
            val out = ByteArrayOutputStream()
            it.compress(Bitmap.CompressFormat.JPEG, 85, out)
            attachments.add(Attachment("camera_${System.currentTimeMillis()}.jpg", "image/jpeg", out.toByteArray()))
        }
    }
    val projectionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        if (res.resultCode == Activity.RESULT_OK && res.data != null) {
            captureScreen(context, res.data!!) { att -> attachments.add(att) }
        }
    }
    fun startScreenCapture() {
        val mgr = context.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projectionLauncher.launch(mgr.createScreenCaptureIntent())
    }

    val speechRecognizer = remember { runCatching { SpeechRecognizer.createSpeechRecognizer(context) }.getOrNull() }
    val tts = remember {
        var t: TextToSpeech? = null
        t = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                val ru = Locale("ru")
                try { t?.language = ru } catch (_: Exception) { }
                val voice = t?.voices?.firstOrNull { v -> v.locale.language == "ru" && !v.isNetworkConnectionRequired }
                    ?: t?.voices?.firstOrNull { v -> v.locale.language == "ru" }
                if (voice != null) try { t?.voice = voice } catch (_: Exception) { }
            }
        }
        t
    }
    fun startVoiceInput() {
        if (speechRecognizer == null || !SpeechRecognizer.isRecognitionAvailable(context)) {
            Toast.makeText(context, "Распознавание речи недоступно", Toast.LENGTH_SHORT).show()
            return
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU")
            putExtra(RecognizerIntent.EXTRA_PROMPT, "Говорите")
        }
        try {
            speechRecognizer.startListening(intent)
            recording = true
            Toast.makeText(context, "Говорите…", Toast.LENGTH_SHORT).show()
        } catch (_: Exception) {
            recording = false
        }
    }
    val micLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) startVoiceInput() else Toast.makeText(context, "Нет доступа к микрофону", Toast.LENGTH_SHORT).show()
    }

    DisposableEffect(Unit) {
        try { tts.language = Locale("ru") } catch (_: Exception) { }
        val listener = object : RecognitionListener {
            override fun onReadyForSpeech(p: Bundle?) {}
            override fun onBeginningOfSpeech() { recording = true }
            override fun onRmsChanged(r: Float) {}
            override fun onBufferReceived(b: ByteArray?) {}
            override fun onEndOfSpeech() { recording = false }
            override fun onError(e: Int) { recording = false; Toast.makeText(context, "ошибка распознавания", Toast.LENGTH_SHORT).show() }
            override fun onResults(r: Bundle?) {
                recording = false
                val res = r?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                if (!res.isNullOrEmpty()) prompt = (prompt + " " + res[0]).trim()
            }
            override fun onPartialResults(r: Bundle?) {}
            override fun onEvent(e: Int, p: Bundle?) {}
        }
        speechRecognizer?.setRecognitionListener(listener)
        onDispose {
            speechRecognizer?.destroy()
            tts.shutdown()
        }
    }

    val listState = rememberLazyListState()

    LaunchedEffect(host) { prefs.edit().putString("host", host).apply() }
    LaunchedEffect(accessToken) { saveSecret(prefs, "http_token_enc", accessToken) }

    fun syncCurrent() {
        val s = sessions.first { it.id == currentId }
        s.messages.clear()
        s.messages.addAll(messages)
        saveSessions(context, sessions)
    }
    fun cancelStreaming() {
        streamCancellation?.cancel()
        requestJob?.cancel()
    }
    fun createNewSession() {
        cancelStreaming()
        syncCurrent()
        val s = Session(UUID.randomUUID().toString(), "Новый чат", mutableListOf())
        sessions.add(s)
        currentId = s.id
    }
    fun deleteSession(id: String) {
        val idx = sessions.indexOfFirst { it.id == id }
        if (idx < 0) return
        if (currentId == id) cancelStreaming()
        sessions.removeAt(idx)
        if (sessions.isEmpty()) sessions.add(Session(UUID.randomUUID().toString(), "Чат 1", mutableListOf()))
        if (currentId == id) currentId = sessions.first().id
        saveSessions(context, sessions)
    }
    fun fetchStatus(h: String, token: String) {
        scope.launch {
            val txt = withContext(Dispatchers.IO) {
                try {
                    val url = URL("${agentBaseUrl(h)}/status")
                    val c = url.openConnection() as HttpURLConnection
                    try {
                        c.connectTimeout = 5000
                        c.readTimeout = 5000
                        if (token.isNotBlank()) c.setRequestProperty("X-Ideal-Agent-Token", token)
                        val stream = if (c.responseCode in 200..299) c.inputStream else c.errorStream
                        val body = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
                        if (c.responseCode in 200..299) body else "HTTP ${c.responseCode}${if (body.isBlank()) "" else ": $body"}"
                    } finally {
                        c.disconnect()
                    }
                } catch (e: Exception) { "ошибка: ${e.message}" }
            }
            messages.add(Message("system", "Статус агента: $txt"))
            syncCurrent()
        }
    }

    fun send() {
        if (busy || (prompt.isBlank() && attachments.isEmpty())) return
        val h = host; val p = prompt; val token = accessToken
        val atts = attachments.toList()
        val trimmed = p.trim()
        if (trimmed.startsWith("/")) {
            when (trimmed) {
                "/clear" -> { cancelStreaming(); tts.stop(); messages.clear(); syncCurrent(); prompt = ""; attachments.clear(); return }
                "/new" -> { tts.stop(); createNewSession(); prompt = ""; attachments.clear(); return }
                "/help" -> {
                    tts.stop()
                    messages.add(Message("system", "Команды: /clear — очистить чат · /new — новый чат · /status — статус агента · /help — справка"))
                    syncCurrent(); prompt = ""; attachments.clear(); return
                }
                "/status" -> { tts.stop(); prompt = ""; attachments.clear(); fetchStatus(h, token); return }
                else -> { /* неизвестная команда — отправим текстом агенту */ }
            }
        }
        prompt = ""
        attachments.clear()
        tts.stop()
        messages.add(Message("user", if (p.isBlank()) "(вложение)" else p))
        if (messages.size == 1) {
            val cur = sessions.first { it.id == currentId }
            if (cur.name == "Новый чат" || cur.name == "Чат 1") cur.name = (if (p.isBlank()) "(вложение)" else p).take(24)
        }
        val agentIdx = messages.size
        val requestSessionId = currentId
        val cancellation = StreamCancellation()
        messages.add(Message("agent", ""))
        busy = true
        streamCancellation = cancellation
        requestJob = scope.launch {
            try {
                askAgentStream(h, p, token, atts, requestSessionId, cancellation) { chunk ->
                    if (currentId == requestSessionId) {
                        val cur = messages.getOrNull(agentIdx)?.text ?: ""
                        messages[agentIdx] = Message("agent", cur + chunk)
                    }
                }
            } catch (_: CancellationException) {
                if (currentId == requestSessionId && messages.getOrNull(agentIdx)?.text.isNullOrBlank()) {
                    messages[agentIdx] = Message("agent", "(ответ отменён)")
                }
            }
            finally {
                if (currentId == requestSessionId) {
                    val reply = messages.getOrNull(agentIdx)?.text ?: ""
                    if (reply.isBlank()) {
                        messages[agentIdx] = Message("agent", "(нет ответа)")
                    } else if (ttsOn) {
                        val spoken = reply.replace(Regex("```[\\s\\S]*?```"), " ")
                            .replace(Regex("!\\[.*?\\]\\(.*?\\)"), " ")
                            .replace(Regex("[*_`#>]"), "").trim()
                        if (spoken.isNotBlank()) tts.speak(spoken, TextToSpeech.QUEUE_FLUSH, null, null)
                    }
                    syncCurrent()
                }
                if (streamCancellation === cancellation) {
                    streamCancellation = null
                    requestJob = null
                    busy = false
                }
            }
        }
    }

    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) listState.scrollToItem(messages.lastIndex)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("ideal-agent", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                        Text("локальный помощник", style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    scrolledContainerColor = MaterialTheme.colorScheme.surface,
                ),
                actions = {
                    FilledIconButton(onClick = { sessionsMenu = true }) {
                        Icon(Icons.Filled.List, contentDescription = "Сессии")
                    }
                    DropdownMenu(expanded = sessionsMenu, onDismissRequest = { sessionsMenu = false }) {
                        DropdownMenuItem(
                            text = { Text("＋ Новый чат", fontWeight = FontWeight.Bold) },
                            onClick = { sessionsMenu = false; createNewSession() },
                        )
                        sessions.forEach { s ->
                            DropdownMenuItem(
                                text = {
                                    Text(
                                        if (s.id == currentId) "• ${s.name}" else s.name,
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = if (s.id == currentId) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
                                    )
                                },
                                onClick = {
                                    sessionsMenu = false
                                    if (s.id != currentId) {
                                        cancelStreaming()
                                        syncCurrent()
                                        currentId = s.id
                                    }
                                },
                                trailingIcon = {
                                    IconButton(onClick = { sessionsMenu = false; deleteSession(s.id) }) {
                                        Icon(Icons.Filled.Delete, contentDescription = "Удалить", modifier = Modifier.size(16.dp))
                                    }
                                },
                            )
                        }
                    }
                    if (messages.isNotEmpty()) {
                        FilledIconButton(onClick = {
                            tts.stop(); messages.clear(); syncCurrent()
                        }) {
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
                    accessToken = accessToken, onAccessToken = { accessToken = it },
                )
            }

            if (messages.isEmpty()) {
                Box(
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    contentAlignment = Alignment.Center,
                ) {
                    Surface(
                        color = MaterialTheme.colorScheme.secondaryContainer.copy(alpha = 0.45f),
                        shape = RoundedCornerShape(24.dp),
                        modifier = Modifier.padding(24.dp),
                    ) {
                        Column(Modifier.padding(22.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("С чего начнём?", style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.SemiBold)
                            Text("Опишите задачу, добавьте файл или приложите скриншот.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
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
                shape = RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .navigationBarsPadding()
                    .padding(start = 10.dp, end = 10.dp, bottom = 14.dp),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                ) {
                    if (attachments.isNotEmpty()) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(bottom = 6.dp),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            attachments.forEachIndexed { idx, a ->
                                AssistChip(
                                    onClick = { attachments.removeAt(idx) },
                                    label = { Text(a.name, style = MaterialTheme.typography.labelSmall) },
                                    trailingIcon = {
                                        Icon(Icons.Filled.Delete, contentDescription = "Убрать", modifier = Modifier.size(14.dp))
                                    },
                                )
                            }
                        }
                    }
                    if (recording) {
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Icon(Icons.Filled.Mic, contentDescription = null, tint = Color.Red, modifier = Modifier.size(18.dp))
                            Text(
                                "Идёт запись… скажите фразу, затем отправьте текст",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.error,
                                modifier = Modifier.weight(1f),
                            )
                            IconButton(onClick = {
                                speechRecognizer?.stopListening()
                                recording = false
                                Toast.makeText(context, "Запись отменена", Toast.LENGTH_SHORT).show()
                            }) {
                                Icon(Icons.Filled.Delete, contentDescription = "Отменить запись", modifier = Modifier.size(18.dp))
                            }
                        }
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.Bottom,
                    ) {
                        Box {
                            IconButton(onClick = { attachMenu = true }) {
                                Text("+", style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            DropdownMenu(expanded = attachMenu, onDismissRequest = { attachMenu = false }) {
                                DropdownMenuItem(
                                    text = { Text("Галерея / файл") },
                                    onClick = { attachMenu = false; pickLauncher.launch("*/*") },
                                )
                                DropdownMenuItem(
                                    text = { Text("Камера") },
                                    onClick = { attachMenu = false; camLauncher.launch(null) },
                                )
                                DropdownMenuItem(
                                    text = { Text("Скриншот экрана") },
                                    onClick = { attachMenu = false; startScreenCapture() },
                                )
                            }
                        }
                        OutlinedTextField(
                            value = prompt,
                            onValueChange = { prompt = it },
                            label = { Text(if (prompt.startsWith("/")) "Команда" else "Сообщение агенту") },
                            singleLine = false,
                            minLines = 1,
                            maxLines = 4,
                            keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                                imeAction = androidx.compose.ui.text.input.ImeAction.Send,
                            ),
                            keyboardActions = androidx.compose.foundation.text.KeyboardActions(onSend = { send() }),
                            modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
                        )
                        IconButton(onClick = {
                            if (recording) { speechRecognizer?.stopListening(); recording = false }
                            else if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) startVoiceInput()
                            else micLauncher.launch(Manifest.permission.RECORD_AUDIO)
                        }) {
                            Icon(Icons.Filled.Mic, contentDescription = "Голосовой ввод", tint = if (recording) Color.Red else MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        IconButton(onClick = { ttsOn = !ttsOn; if (!ttsOn) tts.stop() }) {
                            Icon(if (ttsOn) Icons.Filled.VolumeUp else Icons.Filled.VolumeOff, contentDescription = "Озвучка ответов")
                        }
                        FilledIconButton(
                            onClick = { if (busy) cancelStreaming() else send() },
                            enabled = busy || prompt.isNotBlank() || attachments.isNotEmpty(),
                            modifier = Modifier.size(48.dp),
                        ) {
                            if (busy) {
                                Text("■", style = MaterialTheme.typography.titleMedium)
                            } else {
                                Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Отправить")
                            }
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
    if (msg.role == "system") {
        Row(
            modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
            horizontalArrangement = Arrangement.Center,
        ) {
            Text(
                msg.text,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        return
    }
    val isUser = msg.role == "user"
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Column(horizontalAlignment = if (isUser) Alignment.End else Alignment.Start) {
            Surface(
                color = if (isUser) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.72f),
                shape = if (isUser) RoundedCornerShape(20.dp, 6.dp, 20.dp, 20.dp) else RoundedCornerShape(6.dp, 20.dp, 20.dp, 20.dp),
                modifier = Modifier
                    .widthIn(max = 340.dp)
                    .combinedClickable(
                        onClick = {},
                        onLongClick = { onCopy(msg.text) },
                    ),
            ) {
                if (isUser) {
                    if (msg.text.startsWith("/")) {
                        val sp = msg.text.indexOf(' ')
                        val (cmd, rest) = if (sp > 0) msg.text.substring(0, sp) to msg.text.substring(sp) else msg.text to ""
                        val annotated = AnnotatedString.Builder().apply {
                            pushStyle(SpanStyle(color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold))
                            append(cmd)
                            pop()
                            append(rest)
                        }.toAnnotatedString()
                        Text(annotated, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(12.dp))
                    } else {
                        Text(msg.text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(12.dp))
                    }
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
    val ctx = LocalContext.current
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
                is ImageBlock -> ImageMessage(blk.alt, blk.url, ctx)
                is Hr -> HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
            }
        }
    }
}

@Composable
fun ImageMessage(alt: String, url: String, ctx: Context) {
    if (url.startsWith("data:image")) {
        val bmp = remember(url) {
            try {
                val b64 = url.substringAfter(",")
                val bytes = Base64.decode(b64, Base64.DEFAULT)
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            } catch (_: Exception) { null }
        }
        if (bmp != null) {
            Image(
                bitmap = bmp.asImageBitmap(),
                contentDescription = alt,
                modifier = Modifier.fillMaxWidth().padding(4.dp),
            )
        } else {
            Text("Изображение недоступно", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    } else {
        val link = if (url.startsWith("http")) url else ""
        Text(
            alt.ifBlank { url },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier
                .clickable { if (link.isNotBlank()) openUrl(ctx, link) }
                .padding(4.dp),
        )
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
    accessToken: String, onAccessToken: (String) -> Unit,
) {
    var showToken by remember { mutableStateOf(false) }

    OutlinedCard(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(max = 360.dp)
            .padding(horizontal = 16.dp, vertical = 8.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp).verticalScroll(rememberScrollState())) {
            Text("Подключение к агенту", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = host, onValueChange = onHost,
                label = { Text("Хост:порт агента") },
                singleLine = true, modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
            Text(
                "Обычно 127.0.0.1:8080 для Termux на этом телефоне. Удалённый агент — только https://хост:порт.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )

            OutlinedTextField(
                value = accessToken, onValueChange = onAccessToken,
                label = { Text("Токен HTTP-агента (шифруется)") },
                singleLine = true,
                visualTransformation = if (showToken) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = {
                    IconButton(onClick = { showToken = !showToken }) {
                        Icon(if (showToken) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                            contentDescription = if (showToken) "Скрыть" else "Показать")
                    }
                },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
            Text("Провайдер и API-ключ задаются только в конфиге сервера. Это не передаёт ключ LLM по сети.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 8.dp))
            HorizontalDivider(
                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f),
                modifier = Modifier.padding(top = 14.dp, bottom = 8.dp),
            )
            Text(
                "Версия приложения: ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

suspend fun askAgent(host: String, prompt: String, accessToken: String, attachments: List<Attachment> = emptyList(), sessionId: String = "default"): String {
    return withContext(Dispatchers.IO) {
        try {
            val url = URL("${agentBaseUrl(host)}/message")
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            if (accessToken.isNotBlank()) conn.setRequestProperty("X-Ideal-Agent-Token", accessToken)
            conn.connectTimeout = 120_000
            conn.readTimeout = 120_000
            val obj = JSONObject()
            obj.put("text", prompt)
            obj.put("session_id", sessionId)
            if (attachments.isNotEmpty()) {
                val arr = org.json.JSONArray()
                for (a in attachments) {
                    val o = JSONObject()
                    o.put("name", a.name)
                    o.put("mime", a.mime)
                    o.put("data", Base64.encodeToString(a.bytes, Base64.NO_WRAP))
                    arr.put(o)
                }
                obj.put("attachments", arr)
            }
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

suspend fun askAgentStream(
    host: String, prompt: String, accessToken: String,
    attachments: List<Attachment> = emptyList(),
    sessionId: String = "default",
    cancellation: StreamCancellation? = null,
    onChunk: (String) -> Unit,
): String = withContext(Dispatchers.IO) {
    val full = StringBuilder()
    var conn: HttpURLConnection? = null
    try {
        val url = URL("${agentBaseUrl(host)}/message/stream")
        val connection = url.openConnection() as HttpURLConnection
        conn = connection
        cancellation?.attach(connection)
        connection.requestMethod = "POST"
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/json")
        if (accessToken.isNotBlank()) connection.setRequestProperty("X-Ideal-Agent-Token", accessToken)
        connection.connectTimeout = 120_000
        connection.readTimeout = 120_000
        val obj = JSONObject()
        obj.put("text", prompt)
        obj.put("session_id", sessionId)
        if (attachments.isNotEmpty()) {
            val arr = org.json.JSONArray()
            for (a in attachments) {
                val o = JSONObject()
                o.put("name", a.name)
                o.put("mime", a.mime)
                o.put("data", Base64.encodeToString(a.bytes, Base64.NO_WRAP))
                arr.put(o)
            }
            obj.put("attachments", arr)
        }
        connection.outputStream.use { it.write(obj.toString().toByteArray()) }
        connection.inputStream.bufferedReader().use { reader ->
            var line = reader.readLine()
            while (line != null) {
                if (line.startsWith("data:")) {
                    val payload = line.removePrefix("data:").trim()
                    if (payload == "[DONE]") break
                    try {
                        val chunk = JSONObject(payload).optString("chunk", "")
                        if (chunk.isNotEmpty()) {
                            full.append(chunk)
                            withContext(Dispatchers.Main) { onChunk(chunk) }
                        }
                    } catch (_: Exception) { }
                }
                line = reader.readLine()
            }
        }
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        if (!currentCoroutineContext().isActive) throw CancellationException()
        val msg = "\nошибка: ${e.message}"
        full.append(msg)
        withContext(Dispatchers.Main) { onChunk(msg) }
    } finally {
        conn?.let { cancellation?.clear(it); it.disconnect() }
    }
    full.toString()
}
