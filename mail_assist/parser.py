"""邮件解析器与学术推送提取模块."""

import re
import hashlib
import urllib.parse
import email
from email.header import decode_header
from typing import List, Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class PaperItem:
    """提取自邮件中的单篇论文信息."""
    title: str
    paper_id: str                   # 优先为 arXiv ID，否则为标题 hash
    source: str                     # 'arxiv', 'scholar', 'other'
    url: str
    pdf_url: Optional[str] = None
    authors: str = ""
    snippet: str = ""


@dataclass
class ParsedEmail:
    """解析后的结构化邮件."""
    message_id: str
    subject: str
    sender: str
    date_str: str
    text_content: str
    html_content: str
    attachments: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    is_academic: bool = False
    papers: List[PaperItem] = field(default_factory=list)


class EmailParser:
    """邮件解析与内容抽取器."""

    ARXIV_ID_PATTERN = re.compile(r'(?:arxiv\.org/(?:abs|pdf)/|arXiv:)?(2[0-9]{3}\.[0-9]{4,5}(?:v[0-9]+)?)', re.IGNORECASE)

    @classmethod
    def _unwrap_scholar_url(cls, url: str) -> str:
        """若为 Google Scholar 重定向链接，反解还原出真实论文目标 URL."""
        if not url:
            return url
        try:
            parsed = urllib.parse.urlparse(url)
            if "scholar.google" in parsed.netloc and parsed.path.endswith("scholar_url"):
                qs = urllib.parse.parse_qs(parsed.query)
                if "url" in qs and qs["url"]:
                    return qs["url"][0]
        except Exception:
            pass
        return url

    @classmethod
    def _is_invalid_scholar_link(cls, href: str, title: str) -> bool:
        """严格检查并过滤 Google Scholar 中的学者主页、系统功能按钮与非论文链接."""
        if not href or not title:
            return True
        lower_href = href.lower()
        lower_title = title.strip().lower()

        # 1. 过滤学者个人主页链接 (格式: /citations?user=...)
        if "citations?user=" in lower_href or "/citations?" in lower_href:
            return True

        # 2. 过滤系统管理、快讯退订与通用 Google 链接
        if any(p in lower_href for p in [
            "scholar_alerts", "view_op=cancel_alert", "view_op=list_alerts",
            "accounts.google.com", "google.com/intl", "/preferences"
        ]):
            return True

        # 3. 过滤系统功能按钮或说明文本
        system_texts = [
            "list alerts", "cancel alert", "unsubscribe", "view updates", "manage alerts",
            "privacy policy", "terms of service", "edit alert", "google scholar",
            "this message was sent", "create alert"
        ]
        if any(lower_title.startswith(st) or lower_title == st for st in system_texts):
            return True

        return False

    @classmethod
    def decode_mime_words(cls, s: Optional[str]) -> str:
        """解码 MIME 编码的邮件头字段 (如 Subject, From)."""
        if not s:
            return ""
        decoded_fragments = []
        try:
            for part, encoding in decode_header(s):
                if isinstance(part, bytes):
                    enc = encoding or "utf-8"
                    try:
                        decoded_fragments.append(part.decode(enc, errors="replace"))
                    except (LookupError, UnicodeDecodeError):
                        decoded_fragments.append(part.decode("utf-8", errors="replace"))
                else:
                    decoded_fragments.append(str(part))
            return "".join(decoded_fragments).strip()
        except Exception as e:
            logger.warning(f"[Parser] 解码 MIME 文本异常: {e}, 降级原始文本")
            return str(s)

    @classmethod
    def parse_raw_email(cls, raw_bytes: bytes) -> ParsedEmail:
        """将原始 RFC822 邮件字节流解析为 ParsedEmail 结构体."""
        msg = email.message_from_bytes(raw_bytes)

        # 1. 提取基础头信息
        raw_msg_id = msg.get("Message-ID")
        subject = cls.decode_mime_words(msg.get("Subject", "无主题"))
        sender = cls.decode_mime_words(msg.get("From", "未知发件人"))
        date_str = cls.decode_mime_words(msg.get("Date", ""))

        # 若缺失 Message-ID，通过发件人+时间+主题生成确定性哈希作为唯一键
        if raw_msg_id:
            message_id = raw_msg_id.strip("<> \r\n\t")
        else:
            hash_input = f"{sender}_{date_str}_{subject}".encode("utf-8")
            message_id = f"gen_{hashlib.sha256(hash_input).hexdigest()[:24]}"

        # 2. 遍历正文与附件
        text_parts = []
        html_parts = []
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                if "attachment" in content_disposition:
                    filename = cls.decode_mime_words(part.get_filename())
                    if filename:
                        attachments.append(filename)
                    continue

                payload = part.get_payload(decode=True)
                if not payload:
                    continue

                charset = part.get_content_charset() or "utf-8"
                try:
                    text = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    text = payload.decode("utf-8", errors="replace")

                if content_type == "text/plain":
                    text_parts.append(text)
                elif content_type == "text/html":
                    html_parts.append(text)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                try:
                    text = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    text = payload.decode("utf-8", errors="replace")
                
                if msg.get_content_type() == "text/html":
                    html_parts.append(text)
                else:
                    text_parts.append(text)

        html_content = "\n".join(html_parts)
        text_content = "\n".join(text_parts)

        # 若无纯文本正文，从 HTML 抽取可读文本
        links = []
        if html_content:
            soup = BeautifulSoup(html_content, "html.parser")
            # 移除无效脚本和样式
            for s in soup(["script", "style", "meta", "noscript"]):
                s.decompose()
            # 收集超链接
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if href.startswith("http://") or href.startswith("https://"):
                    links.append(href)
            
            if not text_content:
                text_content = soup.get_text(separator="\n", strip=True)

        # 3. 判定是否为学术论文推送邮件
        is_academic, papers = cls._extract_academic_content(subject, sender, text_content, html_content)

        return ParsedEmail(
            message_id=message_id,
            subject=subject,
            sender=sender,
            date_str=date_str,
            text_content=text_content.strip(),
            html_content=html_content.strip(),
            attachments=attachments,
            links=list(set(links)),
            is_academic=is_academic,
            papers=papers
        )

    @classmethod
    def _extract_academic_content(
        cls, subject: str, sender: str, text: str, html: str
    ) -> Tuple[bool, List[PaperItem]]:
        """检测并抽取邮件中的学术论文条目 (arXiv / Google Scholar / Semantic Scholar 等)."""
        lower_subj = subject.lower()
        lower_sender = sender.lower()
        combined_text = f"{subject} {text}"

        is_scholar = "scholar" in lower_sender or "scholar" in lower_subj or "citations" in lower_subj
        is_arxiv = "arxiv" in lower_sender or "arxiv" in lower_subj

        papers: List[PaperItem] = []

        # 1. 抽取 arXiv 论文条目 (优先从正文匹配 Title 与摘要段落)
        # arXiv 邮件格式通常包含: Title: ... \n Authors: ...
        arxiv_blocks = re.split(r'------------------------------------------------------------------------------|\\\\', combined_text)
        seen_arxiv = set()
        for block in arxiv_blocks:
            m_id = cls.ARXIV_ID_PATTERN.search(block)
            if m_id:
                aid = m_id.group(1).strip()
                if aid and aid not in seen_arxiv:
                    seen_arxiv.add(aid)
                    # 尝试从该 block 提取 Title
                    m_title = re.search(r'Title:\s*(.+?)(?:\r?\n\s*Authors:|\r?\n\s*Categories:|\r?\n\r?\n)', block, re.IGNORECASE | re.DOTALL)
                    title = re.sub(r'\s+', ' ', m_title.group(1)).strip() if m_title else f"arXiv:{aid}"
                    # 尝试从该 block 提取 Authors
                    m_authors = re.search(r'Authors:\s*(.+?)(?:\r?\n\s*Categories:|\r?\n\s*Comments:|\r?\n\r?\n)', block, re.IGNORECASE | re.DOTALL)
                    authors_str = re.sub(r'\s+', ' ', m_authors.group(1)).strip() if m_authors else ""
                    # 提取正文摘要作为 snippet
                    snippet = block.strip()[:1500]
                    papers.append(PaperItem(
                        title=title,
                        paper_id=f"arxiv_{aid}",
                        source="arxiv",
                        url=f"https://arxiv.org/abs/{aid}",
                        pdf_url=f"https://arxiv.org/pdf/{aid}.pdf",
                        authors=authors_str,
                        snippet=snippet
                    ))

        # 兜底正则扫描
        for match in cls.ARXIV_ID_PATTERN.findall(combined_text):
            aid = match if isinstance(match, str) else match[0]
            aid = aid.strip()
            if aid and aid not in seen_arxiv:
                seen_arxiv.add(aid)
                papers.append(PaperItem(
                    title=f"arXiv:{aid}",
                    paper_id=f"arxiv_{aid}",
                    source="arxiv",
                    url=f"https://arxiv.org/abs/{aid}",
                    pdf_url=f"https://arxiv.org/pdf/{aid}.pdf"
                ))
        # 2. 如果包含 HTML，精准结构化解析 Google Scholar 邮件
        if is_scholar and html:
            soup = BeautifulSoup(html, "html.parser")
            # Google Scholar 论文标题严格嵌套在 <h3> 容器中 (避免扫入正文 footer 中的学者个人主页与退订链接)
            h3_elements = soup.find_all("h3")
            for h3 in h3_elements:
                links = h3.find_all("a")
                if not links:
                    continue

                main_link: Optional[Tuple[str, str]] = None
                pdf_link: Optional[str] = None

                for a_tag in links:
                    raw_href = a_tag.get("href", "").strip()
                    a_text = a_tag.get_text(strip=True)
                    if not raw_href or not a_text:
                        continue

                    real_href = cls._unwrap_scholar_url(raw_href)

                    # 识别 [PDF] / [HTML] 独立辅助标签
                    if re.match(r'^\[?(pdf|html)\]?$', a_text, re.IGNORECASE):
                        if not pdf_link:
                            pdf_link = real_href
                    else:
                        # 挑选文本最长的主标题链接
                        if main_link is None or len(a_text) > len(main_link[1]):
                            main_link = (real_href, a_text)

                if not main_link:
                    continue

                real_url, raw_title = main_link

                # 清洗标题前缀，去除开头的 [PDF] / [HTML] 标记与换行多余空格
                clean_title = re.sub(r'^\[(PDF|HTML)\]\s*', '', raw_title, flags=re.IGNORECASE).strip()
                clean_title = re.sub(r'\s+', ' ', clean_title)

                # 严格过滤过短或非论文链接
                if len(clean_title) < 10 or cls._is_invalid_scholar_link(real_url, clean_title):
                    continue

                # 尝试从 h3 的后续兄弟节点提取作者行与摘要 Snippet
                authors_str = ""
                snippet_str = ""
                curr_node = h3.next_sibling
                sibling_texts: List[str] = []
                steps = 0
                while curr_node and len(sibling_texts) < 2 and steps < 10:
                    steps += 1
                    if hasattr(curr_node, "get_text"):
                        txt = curr_node.get_text(strip=True)
                        if txt and not any(kw in txt.lower() for kw in [
                            "this message was sent", "cancel alert", "list alerts", "create alert"
                        ]):
                            sibling_texts.append(txt)
                    curr_node = curr_node.next_sibling

                if sibling_texts:
                    authors_str = sibling_texts[0]
                    if len(sibling_texts) > 1:
                        snippet_str = sibling_texts[1]

                # 识别 arXiv ID
                m = cls.ARXIV_ID_PATTERN.search(real_url) or cls.ARXIV_ID_PATTERN.search(clean_title)
                if m:
                    aid = m.group(1)
                    pid = f"arxiv_{aid}"
                    src = "arxiv"
                    final_pdf_url = pdf_link or f"https://arxiv.org/pdf/{aid}.pdf"
                    final_url = f"https://arxiv.org/abs/{aid}"
                else:
                    pid = f"scholar_{hashlib.md5(clean_title.encode()).hexdigest()[:16]}"
                    src = "scholar"
                    final_pdf_url = pdf_link
                    final_url = real_url

                if not any(p.paper_id == pid for p in papers):
                    papers.append(PaperItem(
                        title=clean_title,
                        paper_id=pid,
                        source=src,
                        url=final_url,
                        pdf_url=final_pdf_url,
                        authors=authors_str,
                        snippet=snippet_str
                    ))
        is_academic_detected = bool(is_arxiv or is_scholar or papers)
        return is_academic_detected, papers
