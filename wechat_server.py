#!/usr/bin/env python3
"""企业微信自建应用 URL 验证服务器 (开源通用版).

用于在企业微信管理后台验证“设置接收消息的服务器 URL”。
"""

import os
import sys
import base64
import struct
import hashlib
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler

# 配置参数 (支持从环境变量读取，或在此填入)
TOKEN = os.environ.get("WECHAT_TOKEN", "YOUR_WECHAT_TOKEN")
ENCODING_AES_KEY = os.environ.get("WECHAT_ENCODING_AES_KEY", "YOUR_ENCODING_AES_KEY")
CORP_ID = os.environ.get("WECHAT_CORP_ID", "YOUR_CORP_ID")
PORT = int(os.environ.get("PORT", 80))

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    print("\n[错误] 缺少 cryptography 库，请执行以下命令安装：")
    print("  apt update && apt install -y python3-cryptography")
    print("  或: pip install cryptography\n")
    sys.exit(1)


def verify_signature(token: str, timestamp: str, nonce: str, echostr: str, msg_signature: str) -> bool:
    items = sorted([token, str(timestamp), str(nonce), str(echostr)])
    computed = hashlib.sha1("".join(items).encode("utf-8")).hexdigest()
    return computed == msg_signature


def decrypt_echostr(encoding_aes_key: str, echostr_b64: str) -> str:
    key = base64.b64decode(encoding_aes_key + "=")
    iv = key[:16]
    ciphertext = base64.b64decode(echostr_b64)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    pad_len = plaintext[-1]
    plaintext = plaintext[:-pad_len]

    msg_len = struct.unpack(">I", plaintext[16:20])[0]
    msg = plaintext[20:20 + msg_len]
    return msg.decode("utf-8")


class WeComHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        params = parse_qs(parsed_url.query)

        msg_signature = params.get("msg_signature", [""])[0]
        timestamp = params.get("timestamp", [""])[0]
        nonce = params.get("nonce", [""])[0]
        echostr = params.get("echostr", [""])[0]

        if not (msg_signature and timestamp and nonce and echostr):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"WeCom Server is running.")
            return

        if not verify_signature(TOKEN, timestamp, nonce, echostr, msg_signature):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Invalid signature")
            return

        try:
            decrypted_msg = decrypt_echostr(ENCODING_AES_KEY, echostr)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(decrypted_msg.encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"success")


def run():
    server_address = ("0.0.0.0", PORT)
    httpd = HTTPServer(server_address, WeComHandler)
    print(f"企业微信回调验证服务启动，监听端口: {PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
