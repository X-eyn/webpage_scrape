import asyncio
import aiohttp
import playwright.async_api as pw
import os
import hashlib
import qrcode
from urllib.parse import urljoin, urlparse
from pathlib import Path
import logging
from datetime import datetime
from PIL import Image
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EnhancedArchiver:
    def __init__(self, output_dir="archived_pages"):
        self.output_dir = output_dir
        self.session = None
        self.browser = None
        self.page = None
        self.base_url = None

    async def setup(self):
        """Initialize browser and session"""
        self.playwright = await pw.async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            args=['--disable-web-security', '--disable-features=IsolateOrigins,site-per-process']
        )
        
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        
        self.session = aiohttp.ClientSession(
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9'
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

    async def handle_dynamic_text(self):
        """Handle dynamic text box states"""
        try:
            # Get all flashcards
            cards = await self.page.query_selector_all('.flashcard')
            
            for card in cards:
                # Capture front state
                await card.evaluate('(element) => element.classList.remove("flipped")')
                await self.page.wait_for_timeout(500)
                
                # Capture back state
                await card.evaluate('(element) => element.classList.add("flipped")')
                await self.page.wait_for_timeout(500)
        except Exception as e:
            logger.error(f"Error handling dynamic text: {str(e)}")

    async def create_video_thumbnail_with_qr(self, video_element, output_path):
        """Create video thumbnail with QR code overlay"""
        try:
            # Get video source
            src = await video_element.evaluate('element => element.querySelector("source").src')
            
            # Generate QR code
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(src)
            qr.make(fit=True)
            qr_image = qr.make_image(fill_color="black", back_color="white")
            
            # Get video thumbnail
            await video_element.screenshot(
                path=str(output_path.parent / "temp_thumb.png")
            )
            
            # Combine thumbnail and QR code
            with Image.open(output_path.parent / "temp_thumb.png") as thumb:
                qr_size = min(thumb.size) // 4
                qr_resized = qr_image.resize((qr_size, qr_size))
                thumb.paste(qr_resized, (thumb.size[0] - qr_size - 10, 10))
                thumb.save(output_path)
            
            # Clean up
            (output_path.parent / "temp_thumb.png").unlink()
            
        except Exception as e:
            logger.error(f"Error creating video thumbnail: {str(e)}")

    async def process_page_content(self):
        """Process and clean up page content"""
        # Hide UI elements
        await self.page.evaluate("""() => {
            const elementsToHide = [
                '.toolbar',
                '.fixed.left-0',
                '.fixed.right-0'
            ];
            elementsToHide.forEach(selector => {
                const element = document.querySelector(selector);
                if (element) element.style.display = 'none';
            });
        }""")
        
        # Handle videos
        videos = await self.page.query_selector_all('video')
        for idx, video in enumerate(videos):
            try:
                thumbnail_path = self.base_dir / f'video_thumbnail_{idx}.png'
                await self.create_video_thumbnail_with_qr(video, thumbnail_path)
                
                # Replace video with thumbnail
                await video.evaluate(f"""(element) => {{
                    const img = document.createElement('img');
                    img.src = "{str(thumbnail_path)}";
                    img.style.width = '100%';
                    img.style.height = 'auto';
                    element.parentNode.replaceChild(img, element);
                }}""")
                
            except Exception as e:
                logger.error(f"Error processing video {idx}: {str(e)}")

        # Handle dynamic text
        await self.handle_dynamic_text()
        await self.page.wait_for_timeout(1000)  # Wait for any transitions

    async def archive_webpage(self, url):
        """Main method to archive a webpage"""
        try:
            await self.setup()
            self.base_dir = self.create_directory(url)
            self.base_url = url
            
            self.page = await self.context.new_page()
            logger.info(f"Navigating to {url}")
            
            self.page.on("dialog", lambda dialog: dialog.accept())
            
            await self.page.goto(url, wait_until='networkidle')
            await self.page.wait_for_timeout(2000)
            
            await self.process_page_content()
            
            pdf_path = self.base_dir / 'book.pdf'
            await self.page.pdf(
                path=str(pdf_path),
                print_background=True,
                format='A4',
                margin={'top': '0', 'bottom': '0', 'left': '0', 'right': '0'},
                scale=1,
                prefer_css_page_size=True
            )
            
            logger.info(f"Successfully archived webpage to {self.base_dir}")
            
        except Exception as e:
            logger.error(f"Error archiving webpage: {str(e)}")
            raise
        finally:
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
    archiver = EnhancedArchiver()
    url = "https://yourepub.com/ebooks/27"
    await archiver.archive_webpage(url)

if __name__ == "__main__":
    asyncio.run(main())