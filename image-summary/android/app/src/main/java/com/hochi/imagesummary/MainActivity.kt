package com.hochi.imagesummary

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.util.Base64
import android.view.View
import android.widget.*
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private lateinit var preview: ImageView
    private lateinit var result: TextView
    private lateinit var endpoint: EditText
    private lateinit var analyze: Button
    private lateinit var choose: Button
    private lateinit var consent: CheckBox
    private val worker = Executors.newSingleThreadExecutor()
    private var image: ByteArray? = null
    private var mime: String? = null
    private val limit = 8 * 1024 * 1024

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val scroll = ScrollView(this)
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 40)
            setBackgroundColor(Color.rgb(243, 245, 250))
        }
        scroll.addView(column)
        fun label(text: String, size: Float = 16f) = TextView(this).apply {
            this.text = text; textSize = size; setTextColor(Color.rgb(31, 42, 66)); setPadding(0, 12, 0, 12)
        }
        column.addView(label("HOCHI / VISION", 13f))
        column.addView(label("이미지를 이해하는\n가장 간단한 방법", 28f))
        column.addView(label("이미지를 고르면 주요 요소와 내용을 한국어로 요약합니다."))
        endpoint = EditText(this).apply {
            hint = "분석 서버 주소 (HTTPS)"; setSingleLine(true)
            setText(getPreferences(MODE_PRIVATE).getString("endpoint", "http://10.0.2.2:8101"))
        }
        column.addView(endpoint)
        column.addView(label("기본 주소는 Android 에뮬레이터용입니다. 실제 기기에는 접근 가능한 HTTPS 서버가 필요합니다.", 12f))
        preview = ImageView(this).apply { adjustViewBounds = true; minimumHeight = 280; setBackgroundColor(Color.WHITE) }
        column.addView(preview, LinearLayout.LayoutParams(-1, 360))
        choose = Button(this).apply {
            text = "갤러리에서 이미지 선택"
            setOnClickListener {
                startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    type = "image/*"; addCategory(Intent.CATEGORY_OPENABLE)
                }, 100)
            }
        }
        column.addView(choose)
        consent = CheckBox(this).apply { text = getString(R.string.consent) }
        column.addView(consent)
        analyze = Button(this).apply { text = "이미지 분석하기"; isEnabled = false; setOnClickListener { submit() } }
        column.addView(analyze)
        result = label("분석 결과가 여기에 표시됩니다.\n실제 분석에는 서버의 AI 연결이 필요합니다.")
        result.setTextIsSelectable(true)
        column.addView(result)
        setContentView(scroll)
        column.setOnApplyWindowInsetsListener { view, insets ->
            view.setPadding(32, insets.systemWindowInsetTop + 24, 32, insets.systemWindowInsetBottom + 24)
            insets
        }
    }

    @Deprecated("Legacy activity result API supported on all target devices")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 100 || resultCode != RESULT_OK) return
        val uri: Uri = data?.data ?: return
        try {
            val kind = contentResolver.getType(uri)
            require(kind in listOf("image/png", "image/jpeg", "image/webp", "image/gif")) { "PNG/JPEG/WebP/GIF 파일을 선택하세요." }
            val bytes = contentResolver.openInputStream(uri)?.use { stream ->
                val buffer = ByteArray(8192)
                val output = ByteArrayOutputStream()
                while (output.size() <= limit) {
                    val count = stream.read(buffer, 0, minOf(buffer.size, limit + 1 - output.size()))
                    if (count < 0) break
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            }
                ?: error("이미지를 읽을 수 없습니다.")
            require(bytes.isNotEmpty() && bytes.size <= limit) { "이미지는 8 MiB 이하여야 합니다." }
            image = bytes; mime = kind
            preview.setImageURI(uri)
            analyze.isEnabled = true
            result.text = getString(R.string.selected, bytes.size / 1024)
        } catch (error: Exception) {
            image = null; analyze.isEnabled = false; preview.setImageDrawable(null)
            result.text = error.message ?: "이미지를 읽을 수 없습니다."
        }
    }

    private fun submit() {
        val bytes = image ?: return
        if (!consent.isChecked) { result.text = "이미지 전송에 동의해 주세요."; return }
        val address = endpoint.text.toString().trim().trimEnd('/')
        try {
            val url = URL(address)
            require(url.protocol == "https" || (BuildConfig.DEBUG && url.protocol == "http" && url.host == "10.0.2.2")) {
                "HTTPS 주소를 사용하세요. 디버그 에뮬레이터 주소만 HTTP를 허용합니다."
            }
        } catch (error: Exception) { result.text = error.message ?: "서버 주소를 확인하세요."; return }
        getPreferences(MODE_PRIVATE).edit().putString("endpoint", address).apply()
        analyze.isEnabled = false; choose.isEnabled = false
        result.text = "이미지를 분석하고 있습니다…"
        val kind = mime
        worker.execute {
            val message = try {
                val connection = URL("$address/api/analyze").openConnection() as HttpURLConnection
                try {
                    connection.requestMethod = "POST"; connection.doOutput = true
                    connection.connectTimeout = 15000; connection.readTimeout = 75000
                    connection.instanceFollowRedirects = false
                    connection.setRequestProperty("Content-Type", "application/json")
                    val payload = JSONObject().put("mime", kind).put("data", Base64.encodeToString(bytes, Base64.NO_WRAP))
                    connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
                    val status = connection.responseCode
                    val stream = if (status in 200..299) connection.inputStream else connection.errorStream
                    val response = stream?.bufferedReader()?.use { it.readText() } ?: error("서버 응답이 없습니다.")
                    val parsed = JSONObject(response)
                    if (status !in 200..299) error(parsed.optString("error", "분석 요청 실패 ($status)"))
                    parsed.getString("summary")
                } finally { connection.disconnect() }
            } catch (error: Exception) { "분석 실패: ${error.message ?: "연결을 확인하세요."}" }
            runOnUiThread {
                if (!isDestroyed) { result.text = message; analyze.isEnabled = image != null; choose.isEnabled = true }
            }
        }
    }

    override fun onDestroy() { worker.shutdownNow(); super.onDestroy() }
}
