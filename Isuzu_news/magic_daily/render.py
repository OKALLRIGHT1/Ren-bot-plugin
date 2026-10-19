import base64
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.request import pathname2url

try:
    from jinja2 import Template
except Exception:
    Template = None

try:
    from playwright.async_api import async_playwright
except Exception:
    async_playwright = None

from .constants import EMPTY_HITOKOTO


class RenderService:
    def __init__(self, plugin_dir: Path, settings: Dict[str, Any], logger):
        self._plugin_dir = plugin_dir
        self._settings = settings or {}
        self._logger = logger
        self._template_path = self._plugin_dir / "daily_news.html"

    def update_settings(self, settings: Dict[str, Any]):
        self._settings = settings or {}

    def missing_image_deps(self):
        missing = []
        if Template is None:
            missing.append("jinja2")
        if async_playwright is None:
            missing.append("playwright")
        return missing

    def can_render_image(self) -> bool:
        return Template is not None and async_playwright is not None

    async def render_image(self, report_data: Dict[str, Any], output_path: Optional[Path] = None) -> str:
        if Template is None:
            raise RuntimeError("jinja2 not installed")
        if async_playwright is None:
            raise RuntimeError("playwright not installed")
        if not self._template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {self._template_path}")

        html_template_str = self._template_path.read_text(encoding="utf-8")
        template = Template(html_template_str)
        presentation = report_data.get("presentation") or {}
        rendered_html = template.render(
            date_info=report_data.get("date_info") or {},
            anime_list=report_data.get("anime_list") or [],
            bili_hotwords=report_data.get("bili_hotwords") or [],
            hitokoto_data=report_data.get("hitokoto_data") or EMPTY_HITOKOTO,
            moyu_list=report_data.get("moyu_list") or [],
            world_news=report_data.get("world_news") or [],
            it_news=report_data.get("it_news") or [],
            presentation=presentation,
        )
        rendered_html = await self._embed_resources(rendered_html)

        style_fix = """
html, body {
  width: 578px;
  margin: 0;
  padding: 0;
  overflow-x: hidden;
}
"""
        rendered_html = rendered_html.replace("</style>", style_fix + "</style>", 1)

        image_path = await self._render_html_with_playwright(rendered_html, output_path=output_path)
        return str(image_path)

    async def _render_html_with_playwright(self, html_content: str, output_path: Optional[Path] = None) -> str:
        temp_html_path = None
        context = None
        try:
            temp_dir = Path(tempfile.gettempdir())
            temp_html_path = temp_dir / f"magic_girl_daily_{os.getpid()}_{uuid.uuid4().hex[:6]}.html"
            temp_html_path.write_text(html_content, encoding="utf-8")

            if output_path is None:
                output_path = temp_html_path.with_suffix(".png")

            dpr = int(self._settings.get("render_dpr", 4))
            dpr = max(1, min(dpr, 6))

            async with async_playwright() as p:
                self._logger.info("启动 Playwright 渲染日报...")
                browser = await p.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(
                        viewport={"width": 1156, "height": 1000},
                        device_scale_factor=dpr,
                    )
                    page = await context.new_page()

                    file_url = f"file://{pathname2url(str(temp_html_path))}"
                    await page.goto(file_url, wait_until="networkidle")
                    await page.wait_for_timeout(1500)

                    wrapper = await page.query_selector(".wrapper")
                    if not wrapper:
                        raise RuntimeError("未找到 .wrapper 元素")
                    box = await wrapper.bounding_box()
                    if not box:
                        raise RuntimeError("无法获取 .wrapper 的尺寸")

                    wrapper_width = int(box["width"])
                    wrapper_height = int(box["height"])

                    viewport_height = max(int(wrapper_height * 1.2), 1000)
                    viewport_width = 1156
                    await page.set_viewport_size({"width": viewport_width, "height": viewport_height})

                    wrapper = await page.query_selector(".wrapper")
                    if not wrapper:
                        raise RuntimeError("未找到 .wrapper 元素 (viewport 调整后)")

                    clip = {
                        "x": int(box["x"]),
                        "y": int(box["y"]),
                        "width": int(box["width"]),
                        "height": int(box["height"]),
                    }
                    await page.screenshot(path=str(output_path), type="png", clip=clip)
                    self._logger.info(f"日报截图完成: {output_path}")
                    return str(output_path)
                finally:
                    try:
                        if context:
                            await context.close()
                    finally:
                        await browser.close()
        finally:
            if temp_html_path and temp_html_path.exists():
                try:
                    temp_html_path.unlink()
                except Exception:
                    pass

    def _file_to_base64(self, file_path: Path) -> Optional[str]:
        try:
            if not file_path.exists():
                self._logger.warning(f"资源文件不存在: {file_path}")
                return None
            file_data = file_path.read_bytes()
            base64_data = base64.b64encode(file_data).decode("utf-8")
            ext = file_path.suffix.lower()
            mime_types = {
                ".otf": "font/opentype",
                ".ttf": "font/ttf",
                ".woff": "font/woff",
                ".woff2": "font/woff2",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".svg": "image/svg+xml",
            }
            mime_type = mime_types.get(ext, "application/octet-stream")
            return f"data:{mime_type};base64,{base64_data}"
        except Exception as exc:
            self._logger.warning(f"转换文件到 base64 失败: {file_path}: {exc}")
            return None

    async def _embed_resources(self, html_template: str) -> str:
        def replace_font(match: re.Match) -> str:
            filename = match.group(1)
            file_path = self._plugin_dir / "res" / "font" / filename
            base64_uri = self._file_to_base64(file_path)
            if base64_uri:
                return f'url("{base64_uri}")'
            return match.group(0)

        html_template = re.sub(
            r'url\(["\']?\./res/font/([^"\')]+)["\']?\)',
            replace_font,
            html_template,
            flags=re.IGNORECASE,
        )

        def replace_image(match: re.Match) -> str:
            filepath = match.group(1)
            if filepath.startswith("icon/") or filepath.startswith("image/"):
                file_path = self._plugin_dir / "res" / filepath
                base64_uri = self._file_to_base64(file_path)
                if base64_uri:
                    return f'src="{base64_uri}"'
            return match.group(0)

        html_template = re.sub(
            r'src=["\']\./res/([^"\']+)["\']',
            replace_image,
            html_template,
            flags=re.IGNORECASE,
        )

        def replace_local_src(match: re.Match) -> str:
            raw = match.group(1)
            if raw.startswith("data:") or raw.startswith("http://") or raw.startswith("https://"):
                return match.group(0)
            file_path = Path(raw)
            if not file_path.is_absolute():
                file_path = (self._plugin_dir / raw).resolve()
            base64_uri = self._file_to_base64(file_path)
            if base64_uri:
                return f'src="{base64_uri}"'
            return match.group(0)

        html_template = re.sub(
            r'src=["\']([^"\']+)["\']',
            replace_local_src,
            html_template,
            flags=re.IGNORECASE,
        )

        return html_template