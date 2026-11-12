package com.jandrext.camvalidator

import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.*
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.Image
import android.media.ImageReader
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Size
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

enum class Status { PASS, WARN, FAIL, INFO }

data class TestResult(val label: String, val status: Status, val detail: String)

/**
 * Abre cada cámara (y cada cámara física detrás de las lógicas), pide frames reales y los analiza.
 * Corre en un hilo de trabajo: NO llamar desde el hilo principal.
 */
class CameraTester(private val ctx: Context, private val log: (String) -> Unit) {

    private val mgr = ctx.getSystemService(CameraManager::class.java)
    private val thread = HandlerThread("cam-validator").also { it.start() }
    private val handler = Handler(thread.looper)
    private val executor = Executor { handler.post(it) }

    private companion object {
        const val FRAMES_NEEDED = 8          // se descartan los primeros para dejar converger AE/AF
        const val TIMEOUT_S = 10L
        const val ZOOM_TARGET = 0.6f
    }

    fun shutdown() { thread.quitSafely() }

    fun runAll(): List<TestResult> {
        val results = mutableListOf<TestResult>()
        fun add(r: TestResult) { results += r; log("  [${r.status}] ${r.label}: ${r.detail}") }

        val ids = CameraInventory.listIds(ctx)
        log("== INVENTARIO (cameraIdList) ==")
        log("IDs expuestos por el HAL: ${ids.joinToString().ifEmpty { "(ninguno)" }}")
        if (ids.isEmpty()) {
            add(TestResult("Inventario", Status.FAIL, "El HAL no expone ninguna cámara"))
            return results
        }
        val infos = ids.associateWith { CameraInventory.describe(ctx, it) }
        for ((id, info) in infos) {
            if (info == null) log("ID $id : no se pudieron leer características") else log(CameraInventory.format(info).trimEnd())
        }

        log("")
        log("== PRUEBAS (frames reales, ${FRAMES_NEEDED} por prueba) ==")
        for ((id, info) in infos) {
            log("-- Cámara lógica/física ID $id ${info?.facing ?: ""}")
            add(probe("ID $id · stream normal", id, null, null))
            if (info == null) continue

            val physical = info.physicalIds.sorted()
            if (physical.isNotEmpty()) {
                val widest = widestPhysical(physical)
                for (p in physical) {
                    val tag = if (p == widest && physical.size > 1) " (más ancha → ultra‑gran angular)" else ""
                    add(probe("ID $id · física $p$tag", id, p, null))
                }
            }

            val zMin = info.zoomMin
            if (zMin != null && zMin < 1.0f) {
                val target = maxOf(ZOOM_TARGET, zMin)
                val expected = if (physical.size > 1) widestPhysical(physical) else null
                add(probe("ID $id · zoom ${"%.2f".format(target)}x", id, null, target, expectedPhysical = expected))
                if (target != zMin) add(probe("ID $id · zoom mínimo ${"%.2f".format(zMin)}x", id, null, zMin))
                add(probe("ID $id · zoom 1.0x (referencia)", id, null, 1.0f))
            } else if (info.facing == "TRASERA") {
                add(TestResult("ID $id · zoom 0.6x", Status.INFO,
                    "El HAL no anuncia zoom < 1.0x en esta cámara (rango ${zMin ?: "n/d"}–${info.zoomMax ?: "n/d"}). " +
                        "El 0.6x debería venir de una lógica trasera con zoom mínimo ≈ 0.6."))
            }
        }
        return results
    }

    /** La física con menor distancia focal = ultra gran angular. */
    private fun widestPhysical(physical: List<String>): String? =
        physical.minByOrNull { pid ->
            CameraInventory.describe(ctx, pid)?.focalLengths?.minOrNull() ?: Float.MAX_VALUE
        }

    // ──────────────────────────────────────────────────────────────────────────────
    private class FrameStats(val mean: Double, val std: Double, val w: Int, val h: Int)

    private fun probe(
        label: String, logicalId: String, physicalId: String?, zoom: Float?, expectedPhysical: String? = null,
    ): TestResult {
        val t0 = SystemClock.elapsedRealtime()
        val camRef = AtomicReference<CameraDevice?>()
        val sessRef = AtomicReference<CameraCaptureSession?>()
        var reader: ImageReader? = null
        val openErr = AtomicInteger(-1)
        val runtimeErr = AtomicInteger(-1)
        val disconnected = AtomicReference(false)
        try {
            // 1) abrir
            val openLatch = CountDownLatch(1)
            mgr.openCamera(logicalId, object : CameraDevice.StateCallback() {
                override fun onOpened(c: CameraDevice) { camRef.set(c); openLatch.countDown() }
                override fun onDisconnected(c: CameraDevice) { disconnected.set(true); c.close(); openLatch.countDown() }
                override fun onError(c: CameraDevice, e: Int) { openErr.set(e); runtimeErr.set(e); c.close(); openLatch.countDown() }
            }, handler)
            if (!openLatch.await(TIMEOUT_S, TimeUnit.SECONDS)) return fail(label, "TIMEOUT abriendo la cámara (>${TIMEOUT_S}s)")
            val cam = camRef.get() ?: return fail(label,
                if (disconnected.get()) "Cámara desconectada al abrir (otra app la usa o el servicio la cerró)"
                else "No abre: ${deviceError(openErr.get())}")
            val tOpen = SystemClock.elapsedRealtime() - t0

            // 2) stream
            val sizeSource = physicalId?.let { runCatching { mgr.getCameraCharacteristics(it) }.getOrNull() }
                ?: mgr.getCameraCharacteristics(logicalId)
            val size = pickSize(sizeSource)
            val frames = AtomicInteger(0)
            val statsRef = AtomicReference<FrameStats?>()
            val firstFrameAt = AtomicReference(0L)
            val doneLatch = CountDownLatch(1)
            val rd = ImageReader.newInstance(size.width, size.height, ImageFormat.YUV_420_888, 3)
            reader = rd
            rd.setOnImageAvailableListener({ r ->
                val img = r.acquireLatestImage() ?: return@setOnImageAvailableListener
                try {
                    val n = frames.incrementAndGet()
                    if (n == 1) firstFrameAt.set(SystemClock.elapsedRealtime())
                    if (n >= FRAMES_NEEDED && statsRef.get() == null) {
                        statsRef.set(analyze(img)); doneLatch.countDown()
                    }
                } finally { img.close() }
            }, handler)

            val cfg = OutputConfiguration(rd.surface)
            if (physicalId != null) cfg.setPhysicalCameraId(physicalId)
            val sessLatch = CountDownLatch(1)
            val sessFail = AtomicReference(false)
            cam.createCaptureSession(SessionConfiguration(
                SessionConfiguration.SESSION_REGULAR, listOf(cfg), executor,
                object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(s: CameraCaptureSession) { sessRef.set(s); sessLatch.countDown() }
                    override fun onConfigureFailed(s: CameraCaptureSession) { sessFail.set(true); sessLatch.countDown() }
                }))
            if (!sessLatch.await(TIMEOUT_S, TimeUnit.SECONDS)) return fail(label, "TIMEOUT creando sesión (stream ${size.width}x${size.height})")
            val sess = sessRef.get()
            if (sess == null || sessFail.get()) return fail(label,
                "onConfigureFailed con stream ${size.width}x${size.height}" + (physicalId?.let { " (física $it)" } ?: "") +
                    " → el HAL rechaza la configuración")
            val tSession = SystemClock.elapsedRealtime() - t0

            // 3) pedir frames
            val activePhysical = AtomicReference<String?>()
            val focalSeen = AtomicReference<Float?>()
            val zoomSeen = AtomicReference<Float?>()
            val captureFailures = AtomicInteger(0)
            val req = cam.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                addTarget(rd.surface)
                set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                if (zoom != null && Build.VERSION.SDK_INT >= 30) set(CaptureRequest.CONTROL_ZOOM_RATIO, zoom)
            }.build()
            sess.setRepeatingRequest(req, object : CameraCaptureSession.CaptureCallback() {
                override fun onCaptureCompleted(s: CameraCaptureSession, r: CaptureRequest, res: TotalCaptureResult) {
                    activePhysical.set(res.get(CaptureResult.LOGICAL_MULTI_CAMERA_ACTIVE_PHYSICAL_ID))
                    focalSeen.set(res.get(CaptureResult.LENS_FOCAL_LENGTH))
                    if (Build.VERSION.SDK_INT >= 30) zoomSeen.set(res.get(CaptureResult.CONTROL_ZOOM_RATIO))
                }
                override fun onCaptureFailed(s: CameraCaptureSession, r: CaptureRequest, f: CaptureFailure) {
                    captureFailures.incrementAndGet()
                }
            }, handler)

            val gotFrames = doneLatch.await(TIMEOUT_S, TimeUnit.SECONDS)
            val tFrames = SystemClock.elapsedRealtime() - t0
            val timing = "abrir ${tOpen}ms · sesión ${tSession}ms · frames ${tFrames}ms · stream ${size.width}x${size.height}"
            if (runtimeErr.get() != -1) return fail(label, "Error en ejecución: ${deviceError(runtimeErr.get())} · $timing")
            if (disconnected.get()) return fail(label, "Se desconectó durante la captura · $timing")
            if (!gotFrames) return fail(label,
                "Sesión OK pero solo ${frames.get()}/$FRAMES_NEEDED frames, ${captureFailures.get()} capturas fallidas → posible fallo del sensor/driver · $timing")

            val st = statsRef.get()!!
            val meta = buildString {
                append("luma ${"%.0f".format(st.mean)}±${"%.0f".format(st.std)}")
                focalSeen.get()?.let { append(" · focal ${"%.2f".format(it)}mm") }
                zoomSeen.get()?.let { append(" · zoom aplicado ${"%.2f".format(it)}x") }
                activePhysical.get()?.let { append(" · física activa $it") }
                append(" · $timing")
            }
            val black = st.mean < 4 && st.std < 2
            val white = st.mean > 250 && st.std < 2
            return when {
                black -> TestResult(label, Status.FAIL, "Frames llegan pero la imagen es NEGRA (¿lente tapado o sensor sin datos?) · $meta")
                white -> TestResult(label, Status.FAIL, "Frames llegan pero la imagen está saturada en blanco · $meta")
                zoom != null && zoomSeen.get() != null && kotlin.math.abs(zoomSeen.get()!! - zoom) > 0.05f ->
                    TestResult(label, Status.WARN, "El HAL aplicó zoom ${"%.2f".format(zoomSeen.get())}x en vez de ${"%.2f".format(zoom)}x · $meta")
                expectedPhysical != null && activePhysical.get() != null && activePhysical.get() != expectedPhysical ->
                    TestResult(label, Status.WARN, "A este zoom se esperaba la ultra gran angular (física $expectedPhysical) pero el HAL usa la ${activePhysical.get()} → el cambio de lente no ocurre · $meta")
                captureFailures.get() > 0 -> TestResult(label, Status.WARN, "OK pero con ${captureFailures.get()} capturas fallidas · $meta")
                else -> TestResult(label, Status.PASS, meta)
            }
        } catch (e: CameraAccessException) {
            return fail(label, "CameraAccessException: ${accessReason(e.reason)} (${e.message})")
        } catch (e: SecurityException) {
            return fail(label, "Sin permiso de cámara o bloqueada por política: ${e.message}")
        } catch (e: IllegalArgumentException) {
            return fail(label, "Configuración inválida/ID no accesible: ${e.message}")
        } catch (e: Exception) {
            return fail(label, "${e.javaClass.simpleName}: ${e.message}")
        } finally {
            runCatching { sessRef.get()?.close() }
            runCatching { camRef.get()?.close() }
            runCatching { reader?.close() }
            SystemClock.sleep(400) // el HAL necesita respirar entre aperturas
        }
    }

    private fun fail(label: String, detail: String) = TestResult(label, Status.FAIL, detail)

    private fun pickSize(c: CameraCharacteristics): Size {
        val sizes = c.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)?.getOutputSizes(ImageFormat.YUV_420_888)
        if (sizes.isNullOrEmpty()) return Size(640, 480)
        val target = 1280L * 720L
        return sizes.filter { it.width.toLong() * it.height >= 640L * 480L }
            .minByOrNull { kotlin.math.abs(it.width.toLong() * it.height - target) } ?: sizes.maxBy { it.width.toLong() * it.height }
    }

    /** Media y desviación del plano Y, muestreando cada 8 px. */
    private fun analyze(img: Image): FrameStats {
        val p = img.planes[0]
        val buf = p.buffer
        val w = img.width; val h = img.height
        var n = 0L; var sum = 0.0; var sumSq = 0.0
        var y = 0
        while (y < h) {
            var x = 0
            while (x < w) {
                val v = (buf.get(y * p.rowStride + x * p.pixelStride).toInt() and 0xFF).toDouble()
                sum += v; sumSq += v * v; n++
                x += 8
            }
            y += 8
        }
        val mean = sum / n
        return FrameStats(mean, kotlin.math.sqrt((sumSq / n - mean * mean).coerceAtLeast(0.0)), w, h)
    }

    private fun deviceError(code: Int) = when (code) {
        CameraDevice.StateCallback.ERROR_CAMERA_IN_USE -> "ERROR_CAMERA_IN_USE (otra app/servicio la tiene)"
        CameraDevice.StateCallback.ERROR_MAX_CAMERAS_IN_USE -> "ERROR_MAX_CAMERAS_IN_USE"
        CameraDevice.StateCallback.ERROR_CAMERA_DISABLED -> "ERROR_CAMERA_DISABLED (política/privacidad)"
        CameraDevice.StateCallback.ERROR_CAMERA_DEVICE -> "ERROR_CAMERA_DEVICE (fallo fatal del dispositivo/driver)"
        CameraDevice.StateCallback.ERROR_CAMERA_SERVICE -> "ERROR_CAMERA_SERVICE (fallo del servicio de cámara/HAL)"
        else -> "código $code"
    }

    private fun accessReason(r: Int) = when (r) {
        CameraAccessException.CAMERA_DISABLED -> "CAMERA_DISABLED"
        CameraAccessException.CAMERA_DISCONNECTED -> "CAMERA_DISCONNECTED"
        CameraAccessException.CAMERA_ERROR -> "CAMERA_ERROR"
        CameraAccessException.CAMERA_IN_USE -> "CAMERA_IN_USE"
        CameraAccessException.MAX_CAMERAS_IN_USE -> "MAX_CAMERAS_IN_USE"
        else -> "reason=$r"
    }
}
