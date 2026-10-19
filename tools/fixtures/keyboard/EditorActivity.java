package io.a10vm.fixture.keyboard;

import android.app.Activity;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

public final class EditorActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(24, 48, 24, 24);
        TextView title = new TextView(this);
        title.setText("输入中文、英文和数字");
        title.setTextSize(22);
        content.addView(title);
        EditText editor = new EditText(this);
        editor.setSingleLine(true);
        editor.setHint("点击这里输入");
        editor.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence text, int start, int count, int after) {}
            public void onTextChanged(CharSequence text, int start, int before, int count) {
                try { Files.write(new File(getFilesDir(), "text.txt").toPath(), text.toString().getBytes(StandardCharsets.UTF_8)); }
                catch (Exception error) { throw new IllegalStateException(error); }
            }
            public void afterTextChanged(Editable text) {}
        });
        content.addView(editor, new LinearLayout.LayoutParams(-1, -2));
        setContentView(content);
        editor.requestFocus();
        editor.postDelayed(() -> getSystemService(InputMethodManager.class).showSoftInput(editor, InputMethodManager.SHOW_IMPLICIT), 500);
    }
}
