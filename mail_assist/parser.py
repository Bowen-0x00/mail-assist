"""邮件解析器与学术推送提取模块."""

import re
import hashlib
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
        # 2. 如果包含 HTML，尝试结构化解析 Google Scholar 邮件
        if is_scholar and html:
            soup = BeautifulSoup(html, "html.parser")
            # Google Scholar 邮件通常用 h3 或特定 class 装载论文标题
            for h3 in soup.find_all(["h3", "a"]):
                link_tag = h3 if h3.name == "a" else h3.find("a")
                if link_tag and link_tag.get("href"):
                    href = link_tag["href"]
                    title = link_tag.get_text(strip=True)
                    # 过滤过短或功能性按钮
                    if len(title) > 15 and not title.lower().startswith(("unsubscribe", "view", "cancel", "email")):
                        # 如果标题里含有 arxiv id
                        m = cls.ARXIV_ID_PATTERN.search(href) or cls.ARXIV_ID_PATTERN.search(title)
                        if m:
                            aid = m.group(1)
                            pid = f"arxiv_{aid}"
                            src = "arxiv"
                            pdf_url = f"https://arxiv.org/pdf/{aid}.pdf"
                        else:
                            pid = f"scholar_{hashlib.md5(title.encode()).hexdigest()[:16]}"
                            src = "scholar"
                            pdf_url = None

                        if not any(p.paper_id == pid for p in papers):
                            papers.append(PaperItem(
                                title=title,
                                paper_id=pid,
                                source=src,
                                url=href,
                                pdf_url=pdf_url
                            ))

        is_academic_detected = bool(is_arxiv or is_scholar or papers)
        return is_academic_detected, papers
