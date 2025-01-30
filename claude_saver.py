import asyncio
import tinycss2
import aiohttp
import playwright.async_api as pw
import os
import hashlib
import re
from urllib.parse import urljoin, urlparse, unquote
from pathlib import Path
import json
import logging
from datetime import datetime
import cssutils
import bs4
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
cssutils.log.setLevel(logging.ERROR)  # Suppress cssutils warnings

class UniversalArchiver:
    def __init__(self, output_dir="archived_pages"):
        self.output_dir = output_dir
        self.session = None
        self.browser = None
        self.page = None
        self.downloaded_resources = set()
        self.base_url = None
        self.css_files = set()
        self.font_files = set()

    async def setup(self):
        """Initialize browser and session"""
        self.playwright = await pw.async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            args=[
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process'
            ]
        )
        
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        # Setup session with required headers
        self.session = aiohttp.ClientSession(
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br'
            }
        )

    def create_directory(self, url):
        """Create unique directory for the webpage"""
        domain = urlparse(url).netloc
        hash_str = hashlib.md5(url.encode()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_path = Path(self.output_dir) / f"{domain}_{hash_str}_{timestamp}"
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    async def extract_media_urls(self):
        """Extract all media URLs from the page"""
        media_urls = set()
        
        try:
            # Extract all images
            images = await self.page.query_selector_all('img')
            for img in images:
                src = await img.get_attribute('src')
                if src and not src.startswith('data:'):
                    media_urls.add(src)
                
                # Check srcset
                srcset = await img.get_attribute('srcset')
                if srcset:
                    urls = re.findall(r'(https?://[^\s]+)', srcset)
                    media_urls.update(urls)
                
                # Check data-src attributes
                data_src = await img.get_attribute('data-src')
                if data_src:
                    media_urls.add(data_src)

            # Extract all videos
            videos = await self.page.query_selector_all('video')
            for video in videos:
                src = await video.get_attribute('src')
                if src:
                    media_urls.add(src)
                
                # Get video sources
                sources = await video.query_selector_all('source')
                for source in sources:
                    src = await source.get_attribute('src')
                    if src:
                        media_urls.add(src)

            # Extract background images
            bg_images = await self.page.evaluate('''() => {
                const elements = Array.from(document.querySelectorAll('*'));
                const bgImages = [];
                elements.forEach(el => {
                    const style = window.getComputedStyle(el);
                    const bg = style.backgroundImage;
                    if (bg && bg !== 'none') {
                        const matches = bg.match(/url\(['"]?(.*?)['"]?\)/);
                        if (matches) bgImages.push(matches[1]);
                    }
                });
                return bgImages;
            }''')
            
            media_urls.update(bg_images)

            # Clean and resolve URLs
            resolved_urls = set()
            for url in media_urls:
                if url and not url.startswith('data:'):
                    try:
                        resolved_url = urljoin(self.base_url, url)
                        resolved_urls.add(resolved_url)
                        logger.info(f"Found media URL: {resolved_url}")
                    except Exception as e:
                        logger.error(f"Error resolving URL {url}: {str(e)}")

            return resolved_urls

        except Exception as e:
            logger.error(f"Error extracting media URLs: {str(e)}")
            return set()

    async def download_resource(self, url, output_path):
        """Download resource with retry mechanism"""
        if url in self.downloaded_resources:
            return

        retries = 3
        for attempt in range(retries):
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': '*/*',
                    'Referer': self.base_url
                }

                async with self.session.get(url, headers=headers) as response:
                    if response.status == 200:
                        # Ensure directory exists
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        # Get total size if available
                        total_size = int(response.headers.get('Content-Length', 0))
                        
                        # Download with progress tracking
                        with open(output_path, 'wb') as f:
                            downloaded = 0
                            chunk_size = 1024 * 1024  # 1MB chunks
                            async for chunk in response.content.iter_chunked(chunk_size):
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size:
                                    progress = (downloaded / total_size) * 100
                                    logger.info(f"Download progress: {progress:.1f}%")
                        
                        self.downloaded_resources.add(url)
                        logger.info(f"Successfully downloaded: {url}")
                        return
                    else:
                        logger.warning(f"Failed to download {url}: Status {response.status}")
                        if attempt < retries - 1:
                            await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Error downloading {url}: {str(e)}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)

    async def extract_styles(self):
        """Extract all CSS styles and resources"""
        try:
            # Get all stylesheet links
            stylesheets = await self.page.evaluate('''() => {
                return Array.from(document.styleSheets).map(sheet => {
                    return sheet.href || (sheet.ownerNode && sheet.ownerNode.textContent);
                }).filter(Boolean);
            }''')
            
            # Get inline styles
            inline_styles = await self.page.evaluate('''() => {
                return Array.from(document.querySelectorAll('style')).map(style => style.textContent);
            }''')
            
            # Get computed styles for all elements
            computed_styles = await self.page.evaluate('''() => {
                const allElements = document.querySelectorAll('*');
                const styles = {};
                allElements.forEach((el, index) => {
                    const computed = window.getComputedStyle(el);
                    const important = [
                        'display', 'position', 'flex', 'grid',
                        'margin', 'padding', 'width', 'height',
                        'color', 'background', 'font', 'border',
                        'box-shadow', 'transform', 'transition',
                        'animation', 'opacity', 'z-index'
                    ];
                    styles[`element-${index}`] = {};
                    important.forEach(prop => {
                        styles[`element-${index}`][prop] = computed.getPropertyValue(prop);
                    });
                });
                return styles;
            }''')
            
            return {
                'stylesheets': stylesheets,
                'inline_styles': inline_styles,
                'computed_styles': computed_styles
            }
            
        except Exception as e:
            logger.error(f"Error extracting styles: {str(e)}")
            return None

    async def download_css_resources(self, css_content, base_url):
        """Download CSS resources (e.g., fonts, images)"""
        try:
            parser = cssutils.CSSParser()
            sheet = tinycss2.parse_stylesheet()
            
            for rule in sheet:
                if rule.type == rule.FONT_FACE_RULE:
                    for prop in rule.style:
                        if prop.name == 'src':
                            urls = re.findall(r'url\((.*?)\)', prop.value)
                            for url in urls:
                                url = url.strip('\'"')
                                if not url.startswith('data:'):
                                    full_url = urljoin(base_url, url)
                                    self.font_files.add(full_url)
                elif rule.type == rule.STYLE_RULE:
                    for prop in rule.style:
                        if prop.name in ['background', 'background-image']:
                            urls = re.findall(r'url\((.*?)\)', prop.value)
                            for url in urls:
                                url = url.strip('\'"')
                                if not url.startswith('data:'):
                                    full_url = urljoin(base_url, url)
                                    self.css_files.add(full_url)
            
            return css_content
        except Exception as e:
            logger.error(f"Error parsing CSS: {str(e)}")
            return css_content

    async def save_computed_styles(self, computed_styles):
        """Save computed styles to a CSS file"""
        try:
            styles_dir = self.base_dir / 'styles'
            styles_dir.mkdir(exist_ok=True)
            
            computed_css = ''
            for element, styles in computed_styles.items():
                computed_css += f'[data-style="{element}"] {{\n'
                for prop, value in styles.items():
                    computed_css += f'  {prop}: {value};\n'
                computed_css += '}\n'
            
            css_path = styles_dir / 'computed.css'
            css_path.write_text(computed_css, encoding='utf-8')
        except Exception as e:
            logger.error(f"Error saving computed styles: {str(e)}")

    async def modify_html_content(self, content, styles):
        """Modify HTML with preserved styles"""
        try:
            soup = BeautifulSoup(content, 'html.parser')
            
            # Add style markers
            for i, element in enumerate(soup.select('*')):
                element['data-style'] = f'element-{i}'
            
            # Create style directory
            styles_dir = self.base_dir / 'styles'
            styles_dir.mkdir(exist_ok=True)
            
            # Process and save external stylesheets
            for i, stylesheet in enumerate(styles['stylesheets']):
                if stylesheet.startswith('http'):
                    async with self.session.get(stylesheet) as response:
                        if response.status == 200:
                            css_content = await response.text()
                            css_content = await self.download_css_resources(css_content, stylesheet)
                            css_path = styles_dir / f'external_{i}.css'
                            css_path.write_text(css_content)
                            
                            link = soup.new_tag('link', rel='stylesheet', href=f'styles/external_{i}.css')
                            soup.head.append(link)
            
            # Add inline styles
            for i, style in enumerate(styles['inline_styles']):
                css_content = await self.download_css_resources(style, self.base_url)
                css_path = styles_dir / f'inline_{i}.css'
                css_path.write_text(css_content)
                
                link = soup.new_tag('link', rel='stylesheet', href=f'styles/inline_{i}.css')
                soup.head.append(link)
            
            # Add computed styles
            await self.save_computed_styles(styles['computed_styles'])
            link = soup.new_tag('link', rel='stylesheet', href='styles/computed.css')
            soup.head.append(link)
            
            return str(soup)
            
        except Exception as e:
            logger.error(f"Error modifying HTML: {str(e)}")
            return content

    async def archive_webpage(self, url):
        """Main method to archive a webpage"""
        try:
            await self.setup()
            self.base_dir = self.create_directory(url)
            self.base_url = url
            
            # Create new page and navigate
            self.page = await self.context.new_page()
            logger.info(f"Navigating to {url}")
            
            # Handle any dialogs automatically
            self.page.on("dialog", lambda dialog: dialog.accept())
            
            # Navigate and wait for load
            await self.page.goto(url, wait_until='networkidle')
            
            # Scroll to load lazy content
            await self.page.evaluate('''
                async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        const distance = 100;
                        const timer = setInterval(() => {
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            
                            if(totalHeight >= document.body.scrollHeight){
                                clearInterval(timer);
                                resolve();
                            }
                        }, 100);
                    });
                }
            ''')
            
            # Wait for dynamic content
            await asyncio.sleep(3)

            # Save page as PDF
            pdf_path = self.base_dir / 'page.pdf'
            await self.page.pdf(
                path=str(pdf_path),
                print_background=True,
                format='A4',
                landscape=True,
                margin={
                    'top': '0.4in',
                    'bottom': '0.4in',
                    'left': '0.4in',
                    'right': '0.4in'
                },
                width='1920px',
                height='1080px',
                 scale=1
            )
            logger.info(f"Saved PDF version to: {pdf_path}")
            
            # Extract and download media
            media_urls = await self.extract_media_urls()
            logger.info(f"Found {len(media_urls)} media files to download")
            
            for url in media_urls:
                try:
                    parsed_url = urlparse(url)
                    file_path = self.base_dir / 'media' / parsed_url.netloc / parsed_url.path.lstrip('/')
                    await self.download_resource(url, file_path)
                except Exception as e:
                    logger.error(f"Error downloading {url}: {str(e)}")
            
            # Extract styles
            styles = await self.extract_styles()
            
            # Get and modify content
            content = await self.page.content()
            modified_content = await self.modify_html_content(content, styles)
            
            # Save HTML
            html_path = self.base_dir / 'index.html'
            html_path.write_text(modified_content, encoding='utf-8')
            
            logger.info(f"Successfully archived webpage to {self.base_dir}")
            
        except Exception as e:
            logger.error(f"Error archiving webpage: {str(e)}")
            raise
        finally:
            if self.page:
                await self.page.close()
            await self.cleanup()

    async def cleanup(self):
        """Clean up resources"""
        if self.session:
            await self.session.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

async def main():
    archiver = UniversalArchiver()
    # Example URL - replace with any webpage you want to archive
    url = "https://yourepub.com/ebooks/27"
    await archiver.archive_webpage(url)

if __name__ == "__main__":
    asyncio.run(main())