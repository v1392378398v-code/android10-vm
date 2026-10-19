#!/usr/bin/env python3
"""Compare handlers with the actual Android 10 Binder method inventory."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
ADAPTERS = {
    "android.security.keystore.IKeystoreService": "PrivateKeyStore",
    "android.os.IVold": "PrivateVolumes",
    "android.os.IStoraged": "PrivateVolumes",
    "android.net.INetd": "GuestNetworks",
    "android.net.wifi.IWifiManager": "GuestWifi",
}


def main():
    inventory = json.loads((ROOT / "artifacts/clear-data/service-api.json").read_text())
    results = {}
    for api, name in ADAPTERS.items():
        code = (ROOT / "guest-runtime/check" / (name + ".java")).read_text()
        cases = set(re.findall(r'case "([^\"]+)"', code))
        cases.update(re.findall(r'"([^\"]+)"\.equals\(method.getName\(\)\)', code))
        actual = {method["name"] for method in inventory[api]}
        native = api == "android.security.keystore.IKeystoreService"
        results[api] = {"methods": len(actual), "backend": "stock native software keystore" if native else name,
                        "handlerBranches": sorted(actual & cases),
                        "missingHandlerBranches": [] if native else sorted(actual - cases),
                        "unknownHandlerBranches": [] if name == "PrivateVolumes" else sorted(cases - actual),
                        "coverageProvesSemantics": False}
    out = ROOT / "docs/evidence/service-api-v33.json"
    out.write_text(json.dumps({"guestSdk": 29, "source": "Android 10 framework and services reflection",
                             "services": results}, indent=2) + "\n", encoding="utf-8")
    for api, result in results.items():
        print(api + ": methods=" + str(result["methods"]) + ", missing=" + str(len(result["missingHandlerBranches"])))


if __name__ == "__main__":
    main()
