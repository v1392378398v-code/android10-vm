plugins {
    id("com.android.application")
    kotlin("android")
}

val miuiTrial = providers.gradleProperty("guestRuntimeProfile").orNull == "miui12"

android {
    namespace = "io.a10vm"
    compileSdk = 35

    defaultConfig {
        applicationId = if (miuiTrial) "io.a10vm.miui" else "io.a10vm"
        minSdk = 28
        targetSdk = 35
        versionCode = if (miuiTrial) 98 else 59
        versionName = if (miuiTrial) "0.2.88-miui12-android9-aosp-ime" else "0.2.49-android9-aosp-ime"
        resValue("string", "app_name", if (miuiTrial) "A10VM MIUI12" else "A10VM")
        ndk { abiFilters += "arm64-v8a" }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    packaging {
        jniLibs.useLegacyPackaging = true
        jniLibs.keepDebugSymbols += "**/*.so"
        jniLibs.excludes += "**/liba10vm-p1-window.so"
    }
    sourceSets.getByName("main") {
        jniLibs.setSrcDirs(listOf(layout.buildDirectory.dir("native-display/jniLibs")))
        assets.setSrcDirs(listOf(layout.buildDirectory.dir("native-display/assets")))
    }
}

dependencies {
    implementation(project(":native-display"))
    implementation(project(":guest-runtime"))
}

tasks.register("verifyNativeDisplay") {
    doLast {
        if (providers.gradleProperty("ciSkipNativeVerify").isPresent) return@doLast
        check(!providers.gradleProperty("bundledGuest").isPresent) { "The native entry uses native-display inputs." }
        check(layout.buildDirectory.file("native-display/assets/native-display-inputs.json").get().asFile.isFile) {
            "Run sh tools/prepare-native-display.sh first."
        }
    }
}
tasks.named("preBuild").configure { dependsOn("verifyNativeDisplay") }
