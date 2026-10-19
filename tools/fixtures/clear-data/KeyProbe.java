package io.a10vm.fixture.cleardata;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.KeyStore;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class KeyProbe {
    private static final String ALIAS = "a10vm-lifecycle-fixture";

    static void verify(Context context) throws Exception {
        KeyStore keys = KeyStore.getInstance("AndroidKeyStore");
        keys.load(null);
        File saved = new File(context.getFilesDir(), "keystore-probe.bin");
        byte[] plaintext = "A10VM key persistence probe".getBytes(StandardCharsets.US_ASCII);
        if (!saved.isFile()) {
            if (keys.containsAlias(ALIAS)) throw new AssertionError("Clear-data retained the application's key");
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            SecretKey key = generator.generateKey();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key);
            byte[] encrypted = cipher.doFinal(plaintext);
            byte[] iv = cipher.getIV();
            byte[] data = new byte[1 + iv.length + encrypted.length];
            data[0] = (byte) iv.length;
            System.arraycopy(iv, 0, data, 1, iv.length);
            System.arraycopy(encrypted, 0, data, 1 + iv.length, encrypted.length);
            Files.write(saved.toPath(), data);
        }
        byte[] data = Files.readAllBytes(saved.toPath());
        int ivLength = data[0] & 255;
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, (SecretKey) keys.getKey(ALIAS, null),
                new GCMParameterSpec(128, Arrays.copyOfRange(data, 1, 1 + ivLength)));
        if (!Arrays.equals(plaintext, cipher.doFinal(data, 1 + ivLength, data.length - 1 - ivLength)))
            throw new AssertionError("Keystore decrypt changed data");
        android.util.Log.i("A10VM-KeyFixture", "AES-GCM persisted key verified");
    }
}
