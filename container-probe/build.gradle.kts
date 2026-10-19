plugins { id("com.android.application") }

dependencies { implementation(project(":native-display")) }

android {
    namespace = "io.a10vm.containerprobe"
    compileSdk = 35
    defaultConfig {
        applicationId = "io.a10vm.containerprobe"
        minSdk = 30
        targetSdk = 35
        versionCode = if (providers.gradleProperty("containerFilesystem").isPresent) 11
            else if (providers.gradleProperty("containerBinder").isPresent) 10
            else if (providers.gradleProperty("containerCompanion").isPresent) 7
            else if (providers.gradleProperty("containerDynamic").isPresent) 6
            else if (providers.gradleProperty("containerRuntime").isPresent) 5
            else if (providers.gradleProperty("containerProperties").isPresent) 4
            else if (providers.gradleProperty("containerGraphics").isPresent) 12 else 1
        versionName = if (providers.gradleProperty("containerFilesystem").isPresent) "g1-rootless-filesystem"
            else if (providers.gradleProperty("containerBinder").isPresent) "p2-hidl-values"
            else if (providers.gradleProperty("containerCompanion").isPresent) "p2-companion"
            else if (providers.gradleProperty("containerDynamic").isPresent) "p2-dynamic"
            else if (providers.gradleProperty("containerRuntime").isPresent) "p2-bootstrap"
            else if (providers.gradleProperty("containerProperties").isPresent) "p2-properties"
            else if (providers.gradleProperty("containerGraphics").isPresent) "p1b-multitouch" else "g1-stage0"
        manifestPlaceholders["surfaceProbeEnabled"] = providers.gradleProperty("containerGraphics").isPresent
        ndk { abiFilters += "arm64-v8a" }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    packaging {
        jniLibs.useLegacyPackaging = true
        jniLibs.keepDebugSymbols += "**/*.so"
    }
    sourceSets.getByName("main") {
        jniLibs.srcDir(layout.buildDirectory.dir("prepared/jniLibs"))
        assets.srcDir(layout.buildDirectory.dir("prepared/assets"))
    }
}

tasks.register("verifyProbeInputs") {
    doLast {
        check(layout.buildDirectory.file("prepared/assets/inputs.json").get().asFile.isFile) {
            "Run sh container-probe/prepare.sh RAW_IMAGE G0_REPORT first."
        }
        if (providers.gradleProperty("containerGraphics").isPresent) {
            check(layout.buildDirectory.file("prepared/assets/graphics-inputs.json").get().asFile.isFile) {
                "Run sh container-probe/graphics/prepare-apk.sh RAW_IMAGE G0_REPORT first."
            }
        }
        if (providers.gradleProperty("containerProperties").isPresent
                || providers.gradleProperty("containerRuntime").isPresent
                || providers.gradleProperty("containerDynamic").isPresent
                || providers.gradleProperty("containerCompanion").isPresent
                || providers.gradleProperty("containerFilesystem").isPresent
                || providers.gradleProperty("containerBinder").isPresent) {
            check(layout.buildDirectory.file("prepared/assets/properties-inputs.json").get().asFile.isFile) {
                "Run sh container-probe/properties/prepare-apk.sh RAW_IMAGE G0_REPORT first."
            }
        }
        if (providers.gradleProperty("containerRuntime").isPresent
                || providers.gradleProperty("containerDynamic").isPresent
                || providers.gradleProperty("containerCompanion").isPresent
                || providers.gradleProperty("containerFilesystem").isPresent
                || providers.gradleProperty("containerBinder").isPresent) {
            check(layout.buildDirectory.file("prepared/assets/runtime-inputs.json").get().asFile.isFile) {
                "Run sh container-probe/runtime/prepare-apk.sh RAW_IMAGE G0_REPORT first."
            }
        }
        if (providers.gradleProperty("containerDynamic").isPresent
                || providers.gradleProperty("containerCompanion").isPresent
                || providers.gradleProperty("containerFilesystem").isPresent
                || providers.gradleProperty("containerBinder").isPresent) {
            check(layout.buildDirectory.file("prepared/assets/dynamic-inputs.json").get().asFile.isFile) {
                "Run sh container-probe/runtime/dynamic/prepare-apk.sh RAW_IMAGE G0_REPORT first."
            }
        }
        if (providers.gradleProperty("containerCompanion").isPresent
                || providers.gradleProperty("containerBinder").isPresent) {
            check(layout.buildDirectory.file("prepared/assets/companion-inputs.json").get().asFile.isFile) {
                "Run sh container-probe/runtime/companion/prepare-apk.sh RAW_IMAGE G0_REPORT first."
            }
        }
        if (providers.gradleProperty("containerBinder").isPresent) {
            check(layout.buildDirectory.file("prepared/assets/binder-inputs.json").get().asFile.isFile) {
                "Run sh container-probe/binder/prepare-apk.sh RAW_IMAGE G0_REPORT first."
            }
            check(layout.buildDirectory.file("prepared/assets/hwbinder-inputs.json").get().asFile.isFile) {
                "Run sh container-probe/hwbinder/prepare-apk.sh RAW_IMAGE G0_REPORT first."
            }
        }
        if (providers.gradleProperty("containerFilesystem").isPresent) {
            check(layout.buildDirectory.file("prepared/assets/filesystem-inputs.json").get().asFile.isFile) {
                "Run sh container-probe/runtime/filesystem/prepare-apk.sh RAW_IMAGE G0_REPORT first."
            }
        }
    }
}
tasks.named("preBuild").configure { dependsOn("verifyProbeInputs") }
