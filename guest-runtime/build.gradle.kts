plugins { id("com.android.library") }

val runtimePrepared = providers.gradleProperty("guestRuntimePrepared")
    .map { rootProject.file(it) }
    .getOrElse(layout.buildDirectory.dir("prepared").get().asFile)

android {
    namespace = "io.a10vm.guestruntime"
    compileSdk = 35
    defaultConfig { minSdk = 28 }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets.getByName("main") {
        jniLibs.srcDir(runtimePrepared.resolve("jniLibs"))
        assets.srcDir(runtimePrepared.resolve("assets"))
    }
}

tasks.register("verifyRuntime") {
    doLast {
        check(runtimePrepared.resolve("assets/guest-runtime-inputs.json").isFile) {
            "Run sh tools/prepare-native-display.sh first."
        }
    }
}
tasks.named("preBuild").configure { dependsOn("verifyRuntime") }

tasks.withType<org.gradle.api.tasks.bundling.Zip>().configureEach {
    isZip64 = true
}
