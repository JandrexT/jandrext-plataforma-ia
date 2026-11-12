package com.jandrext.camvalidator

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build

/** Información del dispositivo y de los paquetes de cámara, para correlacionar con la actualización que rompió el 0.6x. */
object SystemProbe {

    private val CAMERA_PACKAGES = listOf(
        "com.sec.android.app.camera",
        "com.samsung.android.app.cameraassistant",
        "com.samsung.android.camerasdkservice",
        "com.samsung.android.provider.filterprovider",
        "com.google.android.GoogleCamera",
        "com.android.camera",
    )

    fun collect(ctx: Context): String {
        val sb = StringBuilder()
        sb.appendLine("== DISPOSITIVO ==")
        sb.appendLine("Fabricante/Modelo : ${Build.MANUFACTURER} ${Build.MODEL} (${Build.DEVICE})")
        sb.appendLine("Android           : ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
        sb.appendLine("Parche seguridad  : ${Build.VERSION.SECURITY_PATCH}")
        sb.appendLine("Build / firmware  : ${Build.DISPLAY}")
        sb.appendLine("Fingerprint       : ${Build.FINGERPRINT}")
        sb.appendLine("Bootloader/Radio  : ${Build.BOOTLOADER} / ${Build.getRadioVersion()}")
        sb.appendLine()
        sb.appendLine("== PAQUETES DE CÁMARA ==")
        val pm = ctx.packageManager
        for (p in CAMERA_PACKAGES) {
            try {
                val info = pm.getPackageInfo(p, 0)
                val vc = if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else @Suppress("DEPRECATION") info.versionCode.toLong()
                sb.appendLine("$p : ${info.versionName} (code $vc, actualizado ${java.util.Date(info.lastUpdateTime)})")
            } catch (_: PackageManager.NameNotFoundException) {
                sb.appendLine("$p : no instalado / no visible")
            }
        }
        return sb.toString()
    }
}
