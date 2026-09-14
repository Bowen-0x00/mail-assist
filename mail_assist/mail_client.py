"""IMAP 邮件客户端模块."""

import ssl
import imaplib
import urllib.parse
from typing import List, Optional, Tuple
from loguru import logger

try:
    import socks
except ImportError:
    socks = None

from .config import MailboxConfig
from .parser import EmailParser, ParsedEmail


class ProxiedIMAP4_SSL(imaplib.IMAP4_SSL):
    """支持 HTTP / SOCKS5 代理的 IMAP4_SSL 连接器."""

    def __init__(self, host: str, port: int, proxy_url: str, ssl_context: Optional[ssl.SSLContext] = None):
        self.proxy_url = proxy_url
        self.ssl_ctx = ssl_context or ssl.create_default_context()
        super().__init__(host, port, ssl_context=self.ssl_ctx)

    def _create_socket(self, timeout=None):
        if not socks:
            raise RuntimeError("使用代理需要安装 PySocks: pip install PySocks")
        p = urllib.parse.urlparse(self.proxy_url)
        ptype = socks.PROXY_TYPE_SOCKS5 if "socks" in (p.scheme or "").lower() else socks.PROXY_TYPE_HTTP
        sock = socks.socksocket()
        sock.set_proxy(ptype, p.hostname, p.port)
        if timeout:
            sock.settimeout(timeout or 15)
        sock.connect((self.host, self.port))
        return self.ssl_ctx.wrap_socket(sock, server_hostname=self.host)


class IMAPClient:
    """单个邮箱的 IMAP 连接与拉取器."""

    def __init__(self, config: MailboxConfig):
        self.config = config
        self._conn: Optional[imaplib.IMAP4] = None

    def connect(self) -> bool:
        """建立与 IMAP 服务器的连接并完成登录."""
        try:
            if self.config.proxy:
                logger.info(f"[{self.config.name}] 通过指定代理连接: {self.config.proxy}")
                ctx = ssl.create_default_context()
                self._conn = ProxiedIMAP4_SSL(self.config.host, self.config.port, self.config.proxy, ssl_context=ctx)
            elif self.config.ssl:
                ctx = ssl.create_default_context()
                self._conn = imaplib.IMAP4_SSL(self.config.host, self.config.port, ssl_context=ctx)
            else:
                self._conn = imaplib.IMAP4(self.config.host, self.config.port)

            typ, data = self._conn.login(self.config.username, self.config.password)
            if typ != "OK":
                logger.error(f"[{self.config.name}] IMAP 登录失败: {data}")
                return False

            logger.info(f"[{self.config.name}] IMAP 连接并登录成功 ({self.config.username})")
            return True
        except Exception as e:
            logger.error(f"[{self.config.name}] IMAP 连接异常: {e}")
            self._conn = None
            return False

    def disconnect(self):
        """安全断开连接."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def fetch_unseen_emails(self, max_count: int = 10) -> List[ParsedEmail]:
        """拉取收件箱中的未读邮件 (UNSEEN)."""
        if not self._conn:
            if not self.connect():
                return []

        parsed_list: List[ParsedEmail] = []
        try:
            # 选择收件箱
            status, _ = self._conn.select("INBOX", readonly=False)
            if status != "OK":
                logger.warning(f"[{self.config.name}] 无法打开 INBOX")
                return []

            # 检索未读邮件
            typ, data = self._conn.search(None, "UNSEEN")
            if typ != "OK" or not data or not data[0]:
                logger.debug(f"[{self.config.name}] 没有新的未读邮件")
                return []

            msg_ids = data[0].split()
            logger.info(f"[{self.config.name}] 发现 {len(msg_ids)} 封未读邮件，拉取最新 {min(len(msg_ids), max_count)} 封")

            # 取最新的 N 封 (倒序)
            target_ids = msg_ids[-max_count:]
            for mid in target_ids:
                try:
                    res_type, res_data = self._conn.fetch(mid, "(RFC822)")
                    if res_type != "OK" or not res_data or not res_data[0]:
                        continue

                    raw_bytes = res_data[0][1]
                    parsed = EmailParser.parse_raw_email(raw_bytes)
                    parsed_list.append(parsed)
                except Exception as e:
                    logger.error(f"[{self.config.name}] 解析邮件 #{mid} 出错: {e}")
                    continue

        except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError) as e:
            logger.warning(f"[{self.config.name}] 连接断开或操作超时: {e}，将在下次循环重试")
            self.disconnect()
        except Exception as e:
            logger.error(f"[{self.config.name}] 拉取未读邮件未预期异常: {e}")

        return parsed_list
