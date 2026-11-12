plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.jandrext.camvalidator"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.jandrext.camvalidator"
        minSdk = 28            // physical camera IDs (multi-camera) exigen API 28+
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildTypes {
        release { isMinifyEnabled = false }
    }
}
