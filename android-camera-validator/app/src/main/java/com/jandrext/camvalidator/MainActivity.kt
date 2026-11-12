package com.jandrext.camvalidator

import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.provider.MediaStore
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.util.concurrent.Executors

class MainActivity : Activity() {

    private lateinit var output: TextView
    private lateinit var scroll: ScrollView
    private lateinit var runBtn: Button
    private val report = StringBuilder()
    private val worker = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        fun btn(text: String, onClick: () -> Unit) = Button(this).apply {
            this.text = text; isAllCaps = false; setOnClickListener { onClick() }
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        runBtn = btn("▶ Validar cámaras") { startValidation() }
        val row1 = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(runBtn)
            addView(btn("Cámara del sistema") { openSystemCamera() })
        }
        val row2 = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(btn("Copiar informe") { copyReport() })
            addView(btn("Compartir") { shareReport() })
        }
        output = TextView(this).apply {
            typeface = Typeface.MONOSPACE; textSize = 11f; setTextIsSelectable(true)
            setTextColor(Color.parseColor("#E0E0E0")); setPadding(16, 16, 16, 16)
        }
        scroll = ScrollView(this).apply {
            setBackgroundColor(Color.parseColor("#121212"))
            addView(output)
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        val title = TextView(this).apply {
            text = "Cam Validator · Galaxy S26"; textSize = 18f; gravity = Gravity.CENTER
            setTypeface(null, Typeface.BOLD); setPadding(0, 8, 0, 8)
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            addView(title); addView(row1); addView(row2); addView(scroll)
            // Android 15+ dibuja edge‑to‑edge: respetar barras del sistema
            @Suppress("DEPRECATION")
            setOnApplyWindowInsetsListener { v, i ->
                v.setPadding(i.systemWindowInsetLeft, i.systemWindowInsetTop, i.systemWindowInsetRight, i.systemWindowInsetBottom); i
            }
        }
        setContentView(root)
        append(SystemProbe.collect(this))
        append("\nPulsa «Validar cámaras». Cierra otras apps de cámara antes de empezar.\n")
    }

    private fun startValidation() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 1); return
        }
        runBtn.isEnabled = false
        report.setLength(0); output.text = ""
        append(SystemProbe.collect(this))
        worker.execute {
            val tester = CameraTester(this) { line -> runOnUiThread { append(line + "\n") } }
            val results = try { tester.runAll() } catch (e: Exception) {
                runOnUiThread { append("ERROR FATAL en la validación: $e\n") }; emptyList()
            } finally { tester.shutdown() }
            runOnUiThread { append(summary(results)); runBtn.isEnabled = true }
        }
    }

    override fun onRequestPermissionsResult(code: Int, perms: Array<out String>, res: IntArray) {
        super.onRequestPermissionsResult(code, perms, res)
        if (res.firstOrNull() == PackageManager.PERMISSION_GRANTED) startValidation()
        else append("\nPermiso de cámara denegado: sin él no se puede validar.\n")
    }

    private fun summary(r: List<TestResult>): String = buildString {
        val pass = r.count { it.status == Status.PASS }
        val warn = r.count { it.status == Status.WARN }
        val fail = r.count { it.status == Status.FAIL }
        appendLine("\n== RESUMEN ==  PASS $pass · WARN $warn · FAIL $fail · INFO ${r.size - pass - warn - fail}")
        r.filter { it.status == Status.FAIL || it.status == Status.WARN }.forEach {
            appendLine(" ${it.status}: ${it.label}\n    ${it.detail}")
        }
        appendLine("\n== DIAGNÓSTICO ==")
        val zoomFails = r.filter { it.label.contains("zoom") && it.status != Status.PASS && it.status != Status.INFO }
        val physFails = r.filter { it.label.contains("física") && it.status == Status.FAIL }
        val plainFails = r.filter { it.label.contains("stream normal") && it.status == Status.FAIL }
        when {
            r.isEmpty() -> appendLine("Sin resultados.")
            fail + warn == 0 -> appendLine("Todas las cámaras y el zoom bajo 1.0x responden. Si el 0.6x falla en la app de Samsung, el problema está en la app/servicios (versiones arriba), no en el driver.")
            plainFails.isNotEmpty() -> appendLine("Hay cámaras que ni abren/transmiten por el camino normal → fallo de driver/HAL del sensor tras la actualización. Compara la versión de firmware (Build) con la anterior y considera reflash/rollback.")
            physFails.isNotEmpty() -> appendLine("La lógica funciona pero una física falla → el sensor ultra gran angular (o su driver) no responde cuando se le pide directamente.")
            zoomFails.isNotEmpty() -> appendLine("Las cámaras funcionan pero el zoom 0.6x no conmuta/entrega imagen → regresión en la capa de cámara lógica del HAL o en el servicio de Samsung, no en el sensor.")
            else -> appendLine("Revisa los WARN: la imagen llega pero con anomalías.")
        }
        appendLine("\nEnvía este informe completo (Compartir) para analizarlo.")
    }

    private fun openSystemCamera() = try {
        startActivity(Intent(MediaStore.ACTION_IMAGE_CAPTURE))
    } catch (e: Exception) { Toast.makeText(this, "No hay app de cámara: $e", Toast.LENGTH_LONG).show() }

    private fun copyReport() {
        getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("informe", output.text))
        Toast.makeText(this, "Informe copiado", Toast.LENGTH_SHORT).show()
    }

    private fun shareReport() {
        startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"; putExtra(Intent.EXTRA_SUBJECT, "Informe cámaras S26"); putExtra(Intent.EXTRA_TEXT, output.text.toString())
        }, "Compartir informe"))
    }

    private fun append(s: String) {
        report.append(s); output.append(s)
        scroll.post { scroll.fullScroll(ScrollView.FOCUS_DOWN) }
    }
}
