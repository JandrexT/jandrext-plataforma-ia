# Cam Validator (Galaxy S26)

App Android nativa (Kotlin, Camera2, sin dependencias externas) que valida todos los drivers/sensores de cámara
tras la actualización que dejó de funcionar el **0.6x** (ultra gran angular).

## Qué hace
1. Informa modelo, firmware, parche y versión de los paquetes de cámara de Samsung.
2. Lista cada cámara del HAL (lógicas y físicas): focal, sensor, rango de zoom, capacidades.
3. Para cada una abre el dispositivo, crea sesión, pide 8 frames reales y mide luma (detecta imagen negra/saturada, timeouts, errores del HAL).
4. Prueba cada cámara **física** por separado y la lógica trasera en **zoom 0.6x**, comprobando que el HAL conmute a la ultra gran angular.
5. Da un diagnóstico (driver/HAL del sensor vs. capa lógica/zoom vs. app) y permite copiar/compartir el informe.

## Compilar
- **Sin PC:** GitHub → Actions → *Build Cam Validator APK* → Run workflow → descargar el artefacto `app-debug.apk` e instalarlo.
- **Android Studio:** abrir la carpeta `android-camera-validator` y ejecutar.
- **CLI:** `gradle :app:assembleDebug` (Gradle 8.9+, JDK 17, Android SDK 35).

> Nota: el código no se ha compilado ni probado en un dispositivo real aún.
