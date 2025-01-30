import asyncio
import aiohttp
import playwright.async_api as pw
import os
import hashlib
from urllib.parse import urljoin, urlparse
from pathlib import Path
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EnhancedArchiver:
    def __init__(self, output_dir="downloaded_books"):
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

    def create_output_path(self, url):
        """Create output directory and return PDF path"""
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        domain = urlparse(url).netloc
        hash_str = hashlib.md5(url.encode()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return Path(self.output_dir) / f"book_{domain}_{timestamp}.pdf"

    async def handle_dynamic_content(self):
        """Handle both states of dynamic content in a single view"""
        try:
            cards = await self.page.query_selector_all('.flashcard')
            
            for card in cards:
                # Get the content of both states
                front_content = await card.evaluate("""element => {
                    const front = element.querySelector('.front .card-content');
                    return front ? front.innerHTML : '';
                }""")
                
                back_content = await card.evaluate("""element => {
                    const back = element.querySelector('.back .card-content');
                    return back ? back.innerHTML : '';
                }""")
                
                # Replace the flashcard with static content showing both states
                await card.evaluate("""(element, {front, back}) => {
                    const newContent = document.createElement('div');
                    newContent.style.padding = '20px';
                    newContent.style.margin = '20px 0';
                    
                    const frontDiv = document.createElement('div');
                    frontDiv.style.padding = '15px';
                    frontDiv.style.marginBottom = '20px';
                    frontDiv.style.border = '2px solid #4CAF50';
                    frontDiv.style.borderRadius = '8px';
                    frontDiv.style.backgroundColor = '#E8F5E9';
                    frontDiv.innerHTML = front;
                    
                    const backDiv = document.createElement('div');
                    backDiv.style.padding = '15px';
                    backDiv.style.border = '1px solid #BDBDBD';
                    backDiv.style.borderRadius = '8px';
                    backDiv.style.backgroundColor = '#FFFFFF';
                    backDiv.innerHTML = back;
                    
                    newContent.appendChild(frontDiv);
                    newContent.appendChild(backDiv);
                    
                    element.replaceWith(newContent);
                }""", {'front': front_content, 'back': back_content})
                
        except Exception as e:
            logger.error(f"Error handling dynamic content: {str(e)}")

    async def process_videos(self):
        """Process videos to make them clickable in PDF"""
        videos = await self.page.query_selector_all('video')
        for video in videos:
            try:
                # Get video source URL
                video_src = await video.evaluate("""element => {
                    const source = element.querySelector('source');
                    return source ? source.src : '';
                }""")
                
                # Create a clickable thumbnail
                await video.evaluate("""(element, videoUrl) => {
                    const container = document.createElement('div');
                    container.style.position = 'relative';
                    container.style.width = '100%';
                    container.style.maxWidth = '400px';
                    container.style.margin = '20px auto';
                    
                    const link = document.createElement('a');
                    link.href = videoUrl;
                    link.target = '_blank';
                    
                    const thumbnail = document.createElement('div');
                    thumbnail.style.position = 'relative';
                    thumbnail.style.width = '100%';
                    thumbnail.style.paddingBottom = '56.25%';  // 16:9 aspect ratio
                    thumbnail.style.backgroundColor = '#000';
                    thumbnail.style.borderRadius = '8px';
                    thumbnail.style.overflow = 'hidden';
                    
                    const playButton = document.createElement('div');
                    playButton.innerHTML = '▶';
                    playButton.style.position = 'absolute';
                    playButton.style.top = '50%';
                    playButton.style.left = '50%';
                    playButton.style.transform = 'translate(-50%, -50%)';
                    playButton.style.fontSize = '48px';
                    playButton.style.color = '#FFF';
                    
                    const text = document.createElement('div');
                    text.textContent = 'Click to play video';
                    text.style.textAlign = 'center';
                    text.style.marginTop = '10px';
                    text.style.color = '#1a73e8';
                    text.style.textDecoration = 'underline';
                    
                    thumbnail.appendChild(playButton);
                    link.appendChild(thumbnail);
                    container.appendChild(link);
                    container.appendChild(text);
                    
                    element.parentNode.replaceWith(container);
                }""", video_src)
                
            except Exception as e:
                logger.error(f"Error processing video: {str(e)}")

    async def cleanup_page(self):
        """Remove UI elements and prepare page for PDF"""
        await self.page.evaluate("""() => {
            const elementsToRemove = [
                '.toolbar',
                '.fixed.left-0',
                '.fixed.right-0',
                '.rounded-full.border.w-6.h-6'  // Page numbers
            ];
            
            elementsToRemove.forEach(selector => {
                document.querySelectorAll(selector).forEach(el => el.remove());
            });
            
            // Adjust main content
            const content = document.querySelector('.flex.flex-col.items-center.mt-20');
            if (content) {
                content.style.margin = '0';
                content.style.padding = '20px';
            }
        }""")

    async def archive_webpage(self, url):
        """Main method to archive a webpage"""
        try:
            await self.setup()
            output_path = self.create_output_path(url)
            self.base_url = url
            
            self.page = await self.context.new_page()
            logger.info(f"Navigating to {url}")
            
            self.page.on("dialog", lambda dialog: dialog.accept())
            
            await self.page.goto(url, wait_until='networkidle')
            await self.page.wait_for_timeout(2000)
            
            logger.info("Processing page content...")
            await self.cleanup_page()
            await self.handle_dynamic_content()
            await self.process_videos()
            
            logger.info("Generating PDF...")
            await self.page.pdf(
                path=str(output_path),
                format='A4',
                print_background=True,
                margin={'top': '20px', 'right': '20px', 'bottom': '20px', 'left': '20px'},
                scale=0.95  # Slight scale down to ensure content fits
            )
            
            logger.info(f"Successfully saved book to: {output_path}")
            
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
    url = "https://yourepub.com/ebooks/48" 
    await archiver.archive_webpage(url)

if __name__ == "__main__":
    asyncio.run(main())