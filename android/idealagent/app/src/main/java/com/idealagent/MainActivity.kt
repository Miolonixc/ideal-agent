package com.idealagent

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen() {
    var host by remember { mutableStateOf("127.0.0.1:8080") }
    var prompt by remember { mutableStateOf("") }
    var reply by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text("ideal-agent", fontSize = 20.sp)
        OutlinedTextField(
            value = host,
            onValueChange = { host = it },
            label = { Text("Host:port") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        OutlinedTextField(
            value = prompt,
            onValueChange = { prompt = it },
            label = { Text("Сообщение") },
            singleLine = false,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            modifier = Modifier.fillMaxWidth()
        )
        Button(
            onClick = {
                if (!busy && prompt.isNotBlank()) {
                    busy = true
                    val h = host
                    val p = prompt
                    scope.launch {
                        val r = askAgent(h, p)
                        reply = r
                        busy = false
                    }
                }
            },
            enabled = !busy,
            modifier = Modifier.align(Alignment.End)
        ) {
            Text(if (busy) "…" else "Отправить")
        }
        HorizontalDivider()
        Text(
            text = reply.ifBlank { "Ответ появится здесь." },
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .verticalScroll(rememberScrollState())
        )
    }
}

suspend fun askAgent(host: String, prompt: String): String {
    return withContext(Dispatchers.IO) {
        try {
            val url = URL("http://$host/message")
            val conn = url.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.connectTimeout = 120_000
            conn.readTimeout = 120_000
            val body = "{\"text\":" + JSONObject.quote(prompt) + "}"
            conn.outputStream.write(body.toByteArray())
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
