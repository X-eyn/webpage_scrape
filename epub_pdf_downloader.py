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
        """Handle both states of dynamic content while preserving exact original styling"""
        try:
            cards = await self.page.query_selector_all('.flashcard')
            
            for card in cards:
                # Extract exact styles and content
                card_data = await card.evaluate("""element => {
                    // Helper to get computed styles
                    const getStyles = (el) => {
                        const computed = window.getComputedStyle(el);
                        let styles = {};
                        for (let i = 0; i < computed.length; i++) {
                            const prop = computed[i];
                            styles[prop] = computed.getPropertyValue(prop);
                        }
                        return styles;
                    };
                    
                    // Get all necessary elements
                    const frontContent = element.querySelector('.front .card-content');
                    const backContent = element.querySelector('.back .card-content');
                    const frontCard = element.querySelector('.front');
                    const backCard = element.querySelector('.back');
                    
                    return {
                        frontStyles: getStyles(frontCard),
                        backStyles: getStyles(backCard),
                        frontContentStyles: getStyles(frontContent),
                        backContentStyles: getStyles(backContent),
                        frontHTML: frontContent.innerHTML,
                        backHTML: backContent.innerHTML,
                        originalWidth: element.offsetWidth + 'px'
                    };
                }""")
                
                # Create sequential cards with exact styling
                await card.evaluate("""(element, data) => {
                    const container = document.createElement('div');
                    container.style.display = 'flex';
                    container.style.flexDirection = 'column';
                    container.style.width = data.originalWidth;
                    container.style.margin = '0 auto';
                    container.style.gap = '20px';
                    
                    // Front card (green)
                    const frontCard = document.createElement('div');
                    const frontContent = document.createElement('div');
                    Object.assign(frontCard.style, data.frontStyles);
                    Object.assign(frontContent.style, data.frontContentStyles);
                    frontContent.innerHTML = data.frontHTML;
                    frontCard.appendChild(frontContent);
                    container.appendChild(frontCard);
                    
                    // Back card (white)
                    const backCard = document.createElement('div');
                    const backContent = document.createElement('div');
                    Object.assign(backCard.style, data.backStyles);
                    Object.assign(backContent.style, data.backContentStyles);
                    backContent.innerHTML = data.backHTML;
                    backCard.appendChild(backContent);
                    container.appendChild(backCard);
                    
                    // Force vertical layout and proper width
                    frontCard.style.width = '100%';
                    backCard.style.width = '100%';
                    frontCard.style.position = 'relative';
                    backCard.style.position = 'relative';
                    frontCard.style.display = 'block';
                    backCard.style.display = 'block';
                    
                    element.replaceWith(container);
                }""", card_data)
                
        except Exception as e:
            logger.error(f"Error handling dynamic content: {str(e)}")

    async def process_videos(self):
        """Process videos to make them clickable in PDF with direct links"""
        videos = await self.page.query_selector_all('video')
        for video in videos:
            try:
                # Get video source URL
                video_src = await video.evaluate("""element => {
                    const source = element.querySelector('source');
                    return source ? source.src : '';
                }""")
                
                # Create a clickable thumbnail with direct link
                await video.evaluate("""(element, videoUrl) => {
                    const container = document.createElement('div');
                    container.style.position = 'relative';
                    container.style.width = '100%';
                    container.style.maxWidth = '400px';
                    container.style.margin = '20px auto';
                    
                    const link = document.createElement('a');
                    // Use direct link - this is key for PDF clickability
                    link.href = videoUrl;
                    link.style.display = 'block';
                    link.style.textDecoration = 'none';
                    
                    const thumbnail = document.createElement('div');
                    thumbnail.style.position = 'relative';
                    thumbnail.style.width = '100%';
                    thumbnail.style.paddingBottom = '56.25%';  // 16:9 aspect ratio
                    thumbnail.style.backgroundColor = '#000';
                    thumbnail.style.borderRadius = '8px';
                    thumbnail.style.overflow = 'hidden';
                    thumbnail.style.cursor = 'pointer';
                    
                    const playButton = document.createElement('div');
                    playButton.innerHTML = '▶';
                    playButton.style.position = 'absolute';
                    playButton.style.top = '50%';
                    playButton.style.left = '50%';
                    playButton.style.transform = 'translate(-50%, -50%)';
                    playButton.style.fontSize = '48px';
                    playButton.style.color = '#FFF';
                    
                    // Optional text beneath the thumbnail
                    const text = document.createElement('div');  
                    text.textContent = 'Click here to watch the video';
                    text.style.display = 'block';
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
                scale=0.95,
                prefer_css_page_size=True,
                display_header_footer=False
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
    url = "https://yourepub.com/ebooks/48"  # Replace with your URL
    await archiver.archive_webpage(url)

if __name__ == "__main__":
    asyncio.run(main())