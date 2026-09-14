"""学术论文检索、元数据获取与 PDF 智能速读模块."""

import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
import requests
import fitz  # PyMuPDF
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from loguru import logger


@dataclass
class PaperDetail:
    paper_id: str
    title: str
    authors: List[str]
    source: str
    abstract: str
    url: str
    pdf_url: Optional[str] = None
    pdf_snippet: str = ""  # 从 PDF 抽取的核心文本 (Intro + Conclusion)


class ScholarFetcher:
    """学术论文内容与 PDF 阅读抽取器."""

    def __init__(self, cache_dir: str = "data/cache", proxy: Optional[str] = None):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MailAssist-Bot/1.0 (academic paper assistant)"
        })
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
            logger.info(f"[Scholar] 启用代理抓取论文: {proxy}")

    def get_paper_detail(self, paper_id: str, title: str, source: str, url: str, pdf_url: Optional[str] = None, snippet: str = "") -> PaperDetail:
        """根据论文标识或来源综合抓取论文详情与核心正文."""
        clean_aid = self._clean_arxiv_id(paper_id)
        if clean_aid:
            detail = self.fetch_arxiv_metadata(clean_aid)
            if detail:
                if detail.pdf_url:
                    pdf_snip = self.download_and_extract_pdf_sections(detail.pdf_url, f"arxiv_{clean_aid}")
                    detail.pdf_snippet = pdf_snip
                return detail

        # 若非 arXiv 或 arXiv 慢，尝试 Semantic Scholar
        detail = self.fetch_semantic_scholar_metadata(title)
        if detail:
            if detail.pdf_url:
                pdf_snip = self.download_and_extract_pdf_sections(detail.pdf_url, f"scholar_{paper_id}")
                detail.pdf_snippet = pdf_snip
            return detail

        # 最低兜底：保留邮件内自带的 snippet
        return PaperDetail(
            paper_id=paper_id,
            title=title,
            authors=[],
            source=source,
            abstract=snippet or "",
            url=url,
            pdf_url=pdf_url
        )

    def _clean_arxiv_id(self, raw_id: str) -> Optional[str]:
        """清洗提取标准 arXiv ID (如 2403.12345)."""
        m = re.search(r'(2[0-9]{3}\.[0-9]{4,5}(?:v[0-9]+)?)', raw_id)
        return m.group(1) if m else None

    def fetch_arxiv_metadata(self, arxiv_id: str) -> Optional[PaperDetail]:
        """调用 arXiv 官方 API 获取标准元数据与摘要."""
        # 移除版本号 (如 v1, v2) 请求更准确
        clean_id = re.sub(r'v[0-9]+$', '', arxiv_id)
        api_url = f"http://export.arxiv.org/api/query?id_list={clean_id}"

        try:
            resp = self.session.get(api_url, timeout=6)
            if resp.status_code != 200:
                logger.warning(f"[arXiv API] 请求失败 (HTTP {resp.status_code}): {clean_id}")
                return None

            root = ET.fromstring(resp.content)
            # Atom namespace
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entry = root.find("atom:entry", ns)
            if entry is None:
                return None

            title_elem = entry.find("atom:title", ns)
            summary_elem = entry.find("atom:summary", ns)
            
            title = re.sub(r'\s+', ' ', title_elem.text).strip() if title_elem is not None and title_elem.text else f"arXiv:{arxiv_id}"
            abstract = re.sub(r'\s+', ' ', summary_elem.text).strip() if summary_elem is not None and summary_elem.text else ""

            authors = []
            for a in entry.findall("atom:author", ns):
                name_elem = a.find("atom:name", ns)
                if name_elem is not None and name_elem.text:
                    authors.append(name_elem.text.strip())

            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            abs_url = f"https://arxiv.org/abs/{arxiv_id}"

            logger.info(f"[Scholar] 成功获取 arXiv 论文: {title[:50]}...")
            return PaperDetail(
                paper_id=f"arxiv_{arxiv_id}",
                title=title,
                authors=authors,
                source="arxiv",
                abstract=abstract,
                url=abs_url,
                pdf_url=pdf_url
            )
        except Exception as e:
            logger.warning(f"[Scholar] 抓取 arXiv 元数据异常 ({arxiv_id}): {e}")
            return None

    def fetch_semantic_scholar_metadata(self, title: str) -> Optional[PaperDetail]:
        """通过 Semantic Scholar 免费 API 检索论文摘要."""
        if not title or len(title) < 10:
            return None

        # 过滤 arXiv: 前缀
        clean_title = re.sub(r'^arxiv:\S+\s*', '', title, flags=re.IGNORECASE).strip()
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": clean_title,
            "limit": 1,
            "fields": "title,abstract,authors,url,openAccessPdf,tldr"
        }

        try:
            resp = self.session.get(url, params=params, timeout=12)
            if resp.status_code != 200:
                return None

            data = resp.json()
            papers = data.get("data", [])
            if not papers:
                return None

            p = papers[0]
            matched_title = p.get("title", clean_title)
            abstract = p.get("abstract") or ""
            tldr = (p.get("tldr") or {}).get("text")
            if tldr:
                abstract = f"[TLDR]: {tldr}\n\n{abstract}"

            authors = [a.get("name", "") for a in p.get("authors", []) if a.get("name")]
            paper_url = p.get("url") or f"https://scholar.google.com/scholar?q={urllib.parse.quote(clean_title)}"
            
            oa = p.get("openAccessPdf") or {}
            pdf_url = oa.get("url")

            return PaperDetail(
                paper_id=f"s2_{hash(clean_title)}",
                title=matched_title,
                authors=authors,
                source="scholar",
                abstract=abstract,
                url=paper_url,
                pdf_url=pdf_url
            )
        except Exception as e:
            logger.debug(f"[Scholar] Semantic Scholar 查询跳过 ({clean_title[:30]}): {e}")
            return None

    def download_and_extract_pdf_sections(self, pdf_url: str, cache_key: str) -> str:
        """下载开源 PDF 并提取前 2 页 (Intro) 和最后 1 页 (Conclusion)，供大模型精读."""
        safe_key = re.sub(r'[^\w\-_\.]', '_', cache_key)
        pdf_path = os.path.join(self.cache_dir, f"{safe_key}.pdf")

        # 1. 下载 (若未缓存)
        if not os.path.exists(pdf_path):
            try:
                logger.debug(f"[Scholar] 正在下载 PDF 导读: {pdf_url}")
                r = self.session.get(pdf_url, timeout=20, stream=True)
                if r.status_code == 200:
                    with open(pdf_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            f.write(chunk)
                else:
                    return ""
            except Exception as e:
                logger.debug(f"[Scholar] PDF 下载跳过 ({pdf_url}): {e}")
                return ""

        # 2. PyMuPDF 截取提取
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            if total_pages == 0:
                doc.close()
                return ""

            extracted_chunks = []
            # 提取前两页
            for pno in range(min(2, total_pages)):
                extracted_chunks.append(f"--- Page {pno+1} ---\n" + doc[pno].get_text("text"))

            # 如果页面较多，提取最后一页或倒数第二页的 Conclusion
            if total_pages > 3:
                last_pno = total_pages - 1
                extracted_chunks.append(f"--- Conclusion Page {last_pno+1} ---\n" + doc[last_pno].get_text("text"))

            doc.close()
            full_snippet = "\n".join(extracted_chunks)
            # 限制总长度不超过 5000 字符，保留最精华信息，避免 LLM 上下文超标
            return full_snippet[:5000]
        except Exception as e:
            logger.warning(f"[Scholar] PyMuPDF 解析 PDF 异常: {e}")
            return ""
