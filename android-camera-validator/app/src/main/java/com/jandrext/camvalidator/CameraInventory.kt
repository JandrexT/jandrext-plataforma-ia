package com.jandrext.camvalidator

import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.os.Build
import android.util.Size

/** Descripción estática de una cámara (lógica o física) tal como la reporta el HAL. */
data class CamInfo(
    val id: String,
    val facing: String,
    val hwLevel: String,
    val capabilities: List<String>,
    val focalLengths: List<Float>,
    val sensorMm: String,
    val pixelArray: String,
    val zoomMin: Float?,
    val zoomMax: Float?,
    val physicalIds: Set<String>,
    val maxYuv: Size?,
    val maxJpeg: Size?,
)

object CameraInventory {

    fun listIds(ctx: Context): List<String> =
        ctx.getSystemService(CameraManager::class.java).cameraIdList.toList()

    /** Devuelve null si el HAL no deja leer las características de ese id (típico en físicas ocultas). */
    fun describe(ctx: Context, id: String): CamInfo? {
        val mgr = ctx.getSystemService(CameraManager::class.java)
        val c = try { mgr.getCameraCharacteristics(id) } catch (_: Exception) { return null }
        return describe(id, c)
    }

    fun describe(id: String, c: CameraCharacteristics): CamInfo {
        val facing = when (c.get(CameraCharacteristics.LENS_FACING)) {
            CameraCharacteristics.LENS_FACING_FRONT -> "FRONTAL"
            CameraCharacteristics.LENS_FACING_BACK -> "TRASERA"
            CameraCharacteristics.LENS_FACING_EXTERNAL -> "EXTERNA"
            else -> "?"
        }
        val level = when (c.get(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL)) {
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LEGACY -> "LEGACY"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_LIMITED -> "LIMITED"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_FULL -> "FULL"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_3 -> "LEVEL_3"
            CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL_EXTERNAL -> "EXTERNAL"
            else -> "?"
        }
        val caps = (c.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ?: IntArray(0)).map { capName(it) }
        val focal = (c.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS) ?: FloatArray(0)).toList()
        val sensor = c.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE)
        val pix = c.get(CameraCharacteristics.SENSOR_INFO_PIXEL_ARRAY_SIZE)
        val zoom = if (Build.VERSION.SDK_INT >= 30) c.get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE) else null
        val map = c.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        fun maxSize(fmt: Int) = map?.getOutputSizes(fmt)?.maxByOrNull { it.width.toLong() * it.height }
        return CamInfo(
            id = id,
            facing = facing,
            hwLevel = level,
            capabilities = caps,
            focalLengths = focal,
            sensorMm = sensor?.let { "%.2fx%.2f mm".format(it.width, it.height) } ?: "?",
            pixelArray = pix?.let { "${it.width}x${it.height}" } ?: "?",
            zoomMin = zoom?.lower,
            zoomMax = zoom?.upper,
            physicalIds = if (Build.VERSION.SDK_INT >= 28) c.physicalCameraIds else emptySet(),
            maxYuv = maxSize(ImageFormat.YUV_420_888),
            maxJpeg = maxSize(ImageFormat.JPEG),
        )
    }

    private fun capName(v: Int) = when (v) {
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_BACKWARD_COMPATIBLE -> "BACKWARD_COMPATIBLE"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR -> "MANUAL_SENSOR"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_RAW -> "RAW"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_BURST_CAPTURE -> "BURST_CAPTURE"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA -> "LOGICAL_MULTI_CAMERA"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_DEPTH_OUTPUT -> "DEPTH_OUTPUT"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_ULTRA_HIGH_RESOLUTION_SENSOR -> "ULTRA_HIGH_RES"
        CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_SECURE_IMAGE_DATA -> "SECURE_IMAGE_DATA"
        else -> "CAP_$v"
    }

    fun format(i: CamInfo, indent: String = ""): String = buildString {
        appendLine("${indent}ID ${i.id} · ${i.facing} · HW ${i.hwLevel}")
        appendLine("$indent  focal(mm): ${i.focalLengths.joinToString { "%.2f".format(it) }} · sensor ${i.sensorMm} · ${i.pixelArray}px")
        appendLine("$indent  zoom: ${i.zoomMin?.let { "%.2f".format(it) } ?: "n/d"}x – ${i.zoomMax?.let { "%.1f".format(it) } ?: "n/d"}x")
        appendLine("$indent  YUV máx ${i.maxYuv ?: "?"} · JPEG máx ${i.maxJpeg ?: "?"}")
        appendLine("$indent  caps: ${i.capabilities.joinToString()}")
        if (i.physicalIds.isNotEmpty()) appendLine("$indent  físicas: ${i.physicalIds.sorted().joinToString()}")
    }
}
