#!/usr/bin/env python3
"""Read WebView layout metrics over its local DevTools socket, without page content."""
import argparse
import base64
import hashlib
import http.client
import json
import os
import socket
import struct
from urllib.parse import urlsplit

EXPRESSION = """JSON.stringify({
  visible: document.visibilityState,
  screen: {width: screen.width, height: screen.height,
    availWidth: screen.availWidth, availHeight: screen.availHeight},
  window: {width: innerWidth, height: innerHeight, outerWidth, outerHeight},
  dpr: devicePixelRatio,
  viewport: window.visualViewport && {width: visualViewport.width,
    height: visualViewport.height, scale: visualViewport.scale,
    left: visualViewport.offsetLeft, top: visualViewport.offsetTop},
  viewportMeta: Array.from(document.querySelectorAll('meta[name=viewport]'))
    .map(e => e.content),
  document: {width: document.documentElement.clientWidth,
    height: document.documentElement.clientHeight,
    scrollWidth: document.documentElement.scrollWidth},
  fontSizes: {root: getComputedStyle(document.documentElement).fontSize,
    body: document.body && getComputedStyle(document.body).fontSize},
  launchButtons: Array.from(document.querySelectorAll('body *')).filter(e =>
    e.children.length === 0 && /\u6253\u5f00(?:APP|\u5c0f\u7a0b\u5e8f)/i.test(e.textContent))
    .slice(0, 8).map(e => {
      const layers=[];
      for(let p=e; p && layers.length < 5; p=p.parentElement) {
        const r=p.getBoundingClientRect(), s=getComputedStyle(p);
        layers.push({tag:p.tagName, id:p.id, classes:p.className,
          x:r.x, y:r.y, width:r.width, height:r.height,
          cssWidth:s.width, cssHeight:s.height, transform:s.transform,
          transformOrigin:s.transformOrigin, position:s.position,
          zoom:s.zoom, overflow:s.overflow, borderRadius:s.borderRadius});
        for (const pseudo of [null, '::before', '::after']) {
          const style=getComputedStyle(p,pseudo), key=pseudo || 'self';
          layers[layers.length-1][key]={content:style.content, display:style.display,
            width:style.width, height:style.height, transform:style.transform,
            background:style.background, backgroundClip:style.backgroundClip,
            padding:style.padding, border:style.border, boxSizing:style.boxSizing};
        }
      }
      return {text:e.textContent.trim(), layers};
    }),
  largeElements: Array.from(document.querySelectorAll('body *')).map(e => {
    const r=e.getBoundingClientRect();
    return {tag:e.tagName, width:r.width, height:r.height, x:r.x, y:r.y};
  }).filter(e => e.width > innerWidth * 1.5 || e.height > innerHeight * 3)
    .sort((a,b) => b.width-a.width).slice(0, 12),
  videos: Array.from(document.querySelectorAll('video')).map(e => {
    const r=e.getBoundingClientRect();
    return {width:r.width, height:r.height, intrinsicWidth:e.videoWidth,
      intrinsicHeight:e.videoHeight, time:e.currentTime, readyState:e.readyState,
      paused:e.paused, error:e.error && e.error.code,
      decodedFrames:e.webkitDecodedFrameCount, droppedFrames:e.webkitDroppedFrameCount};
  }),
  frames: Array.from(document.querySelectorAll('iframe')).map(e => {
    const r = e.getBoundingClientRect();
    return {x:r.x, y:r.y, width:r.width, height:r.height};
  }),
  images: Array.from(document.images).slice(0, 24).map(e => {
    const r = e.getBoundingClientRect();
    return {x:r.x, y:r.y, width:r.width, height:r.height,
      intrinsicWidth:e.naturalWidth, intrinsicHeight:e.naturalHeight};
  })
})"""


def connect(name):
    if name.startswith("tcp:"):
        return socket.create_connection(("127.0.0.1", int(name[4:])), timeout=5)
    stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stream.settimeout(5)
    stream.connect("\0" + name)
    return stream


def targets(name):
    stream = connect(name)
    stream.sendall(b"GET /json/list HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
    response = http.client.HTTPResponse(stream)
    response.begin()
    try:
        if response.status != 200:
            raise RuntimeError("DevTools HTTP status " + str(response.status))
        return json.loads(response.read())
    finally:
        stream.close()


def read_exact(stream, size):
    output = bytearray()
    while len(output) < size:
        chunk = stream.recv(size - len(output))
        if not chunk:
            raise EOFError("DevTools connection closed")
        output.extend(chunk)
    return bytes(output)


def send_frame(stream, payload, opcode=1):
    size = len(payload)
    header = bytes([0x80 | opcode])
    if size < 126:
        header += bytes([0x80 | size])
    elif size < 65536:
        header += bytes([0x80 | 126]) + struct.pack("!H", size)
    else:
        header += bytes([0x80 | 127]) + struct.pack("!Q", size)
    mask = os.urandom(4)
    stream.sendall(header + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload)))


def call(name, path, method, params):
    with connect(name) as stream:
        key = base64.b64encode(os.urandom(16)).decode()
        request = ("GET " + path + " HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                   "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: " + key + "\r\n\r\n")
        stream.sendall(request.encode())
        header = bytearray()
        while not header.endswith(b"\r\n\r\n"):
            header.extend(read_exact(stream, 1))
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        if header.split(b"\r\n", 1)[0].split()[1:2] != [b"101"] or accept not in header:
            raise RuntimeError("DevTools WebSocket handshake failed")
        send_frame(stream, json.dumps({"id": 1, "method": method, "params": params}).encode())
        message = bytearray()
        while True:
            first, second = read_exact(stream, 2)
            size = second & 127
            if size == 126:
                size = struct.unpack("!H", read_exact(stream, 2))[0]
            elif size == 127:
                size = struct.unpack("!Q", read_exact(stream, 8))[0]
            if size > 1024 * 1024:
                raise ValueError("Unexpected DevTools message size")
            mask = read_exact(stream, 4) if second & 128 else None
            payload = read_exact(stream, size)
            if mask:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            opcode = first & 15
            if opcode == 8:
                raise EOFError("DevTools WebSocket closed")
            if opcode == 9:
                send_frame(stream, payload, 10)
                continue
            if opcode not in (0, 1):
                continue
            message.extend(payload)
            if not first & 128:
                continue
            result = json.loads(message)
            message.clear()
            if result.get("id") != 1:
                continue
            if "error" in result or "exceptionDetails" in result.get("result", {}):
                raise RuntimeError("WebView metric evaluation failed")
            return result["result"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()
    output = []
    for target in targets(args.socket):
        if target.get("type") != "page" or not target.get("webSocketDebuggerUrl"):
            continue
        page = {"view": json.loads(target.get("description") or "{}")}
        path = urlsplit(target["webSocketDebuggerUrl"]).path
        try:
            page["layout"] = call(args.socket, path, "Page.getLayoutMetrics", {})
            result = call(args.socket, path, "Runtime.evaluate", {
                "expression": EXPRESSION, "returnByValue": True, "timeout": 1000})
            page["metrics"] = json.loads(result["result"]["value"])
        except (RuntimeError, TimeoutError) as failure:
            page["error"] = str(failure)
        output.append(page)
    print(json.dumps({"pages": output}, indent=2))


if __name__ == "__main__":
    main()
