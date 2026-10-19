package io.a10vm.guestruntime;

import java.io.ByteArrayInputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.OutputKeys;
import javax.xml.transform.Transformer;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

final class HostDeviceManifest {
    static void configure(Path manifest, Set<String> unavailableHals) throws Exception {
        if (unavailableHals.isEmpty()) return;
        org.w3c.dom.Document document = DocumentBuilderFactory.newInstance().newDocumentBuilder()
                .parse(new ByteArrayInputStream(Files.readAllBytes(manifest)));
        NodeList services = document.getDocumentElement().getChildNodes();
        boolean changed = false;
        for (int i = services.getLength() - 1; i >= 0; --i) {
            Node service = services.item(i);
            if (!(service instanceof Element) || !"hal".equals(service.getNodeName())) continue;
            NodeList fields = service.getChildNodes();
            for (int j = 0; j < fields.getLength(); ++j) {
                Node field = fields.item(j);
                if ("name".equals(field.getNodeName()) && unavailableHals.contains(field.getTextContent().trim())) {
                    service.getParentNode().removeChild(service);
                    changed = true;
                    break;
                }
            }
        }
        if (!changed) return;
        Transformer transformer = TransformerFactory.newInstance().newTransformer();
        transformer.setOutputProperty(OutputKeys.ENCODING, "UTF-8");
        try (java.io.OutputStream output = Files.newOutputStream(manifest)) {
            transformer.transform(new DOMSource(document), new StreamResult(output));
        }
    }
}
