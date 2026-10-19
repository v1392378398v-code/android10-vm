package io.a10vm.guestruntime;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.Collections;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

public final class HostDeviceManifestTest {
    private static final String VIBRATOR = "android.hardware.vibrator";

    private static int count(Path path, String name) throws Exception {
        Document document = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(path.toFile());
        NodeList services = document.getDocumentElement().getElementsByTagName("hal");
        int count = 0;
        for (int i = 0; i < services.getLength(); ++i) {
            NodeList fields = services.item(i).getChildNodes();
            for (int j = 0; j < fields.getLength(); ++j) {
                Node field = fields.item(j);
                if ("name".equals(field.getNodeName()) && name.equals(field.getTextContent().trim())) count++;
            }
        }
        return count;
    }

    public static void main(String[] args) throws Exception {
        byte[] original = Files.readAllBytes(Paths.get(args[0]));
        Path manifest = Paths.get(args[1]);
        Files.write(manifest, original);
        HostDeviceManifest.configure(manifest, Collections.singleton(VIBRATOR));
        if (count(manifest, VIBRATOR) != 0 || count(manifest, "android.hardware.sensors") != 1 ||
                count(manifest, "android.hardware.health") != 1)
            throw new AssertionError("Unavailable host HAL remains declared or available HAL was removed");
        Files.write(manifest, original);
        HostDeviceManifest.configure(manifest, Collections.emptySet());
        if (!Arrays.equals(original, Files.readAllBytes(manifest)) || count(manifest, VIBRATOR) != 1)
            throw new AssertionError("Available host vibrator declaration changed");
        Files.write(manifest, ("<manifest version=\"2.0\" type=\"device\"><hal format=\"aidl\">" +
                "<name> " + VIBRATOR + " </name><version>1</version><fqname>IVibrator/default</fqname>" +
                "</hal><hal format=\"hidl\"><name>android.hardware.sensors</name>" +
                "<interface><name>" + VIBRATOR + "</name></interface></hal></manifest>")
                .getBytes(StandardCharsets.UTF_8));
        HostDeviceManifest.configure(manifest, Collections.singleton(VIBRATOR));
        if (count(manifest, VIBRATOR) != 0 || count(manifest, "android.hardware.sensors") != 1)
            throw new AssertionError("HAL filtering depends on version, transport, or nested interface names");
        System.out.println("host_device_manifest_capabilities_complete=1");
    }
}
