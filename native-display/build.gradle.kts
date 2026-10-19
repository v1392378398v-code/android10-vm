plugins { id("com.android.library") }

android {
    namespace = "io.a10vm.nativedisplay"
    compileSdk = 35
    defaultConfig { minSdk = 28 }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets.getByName("main").jniLibs.srcDir(layout.buildDirectory.dir("prepared/jniLibs"))
}

tasks.register("verifyRenderer") {
    doLast {
        check(layout.buildDirectory.file("prepared/jniLibs/arm64-v8a/liba10vm-desktop-window.so").get().asFile.isFile) {
            "Run sh tools/prepare-native-display.sh first."
        }
    }
}
tasks.named("preBuild").configure { dependsOn("verifyRenderer") }
