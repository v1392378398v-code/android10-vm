package io.a10vm.fixture.installer;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.StrictMode;
import android.widget.TextView;
import java.io.File;

public final class InstallActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView text = new TextView(this);
        text.setText("Package installation fixture");
        setContentView(text);
        String path = getIntent().getStringExtra("apk");
        if (path == null || state != null) return;
        StrictMode.setVmPolicy(new StrictMode.VmPolicy.Builder().build());
        startActivity(new Intent(Intent.ACTION_VIEW)
            .setDataAndType(Uri.fromFile(new File(path)), "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));
    }
}
