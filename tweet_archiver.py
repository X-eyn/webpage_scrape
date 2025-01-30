import os
import re
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from yt_dlp import YoutubeDL

def download_tweet(url):
    # Setup directories
    tweet_id = re.search(r'/status/(\d+)', url).group(1)
    username = re.search(r'/([^/]+)/status', url).group(1)
    folder_name = f"{username}_{tweet_id}"
    media_dir = os.path.join(folder_name, "media")
    os.makedirs(media_dir, exist_ok=True)

    # Configure Chrome
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        # Load page
        driver.get(url)
        time.sleep(5)  # Wait for initial load

        # Click consent cookie button if present
        try:
            driver.find_element(By.XPATH, "//span[contains(text(),'Accept')]").click()
            time.sleep(1)
        except:
            pass

        # Get page source
        html = driver.page_source

        # Find video URLs
        video_urls = []
        for element in driver.find_elements(By.TAG_NAME, 'video'):
            video_urls.append(element.get_attribute('src'))

        # Find image URLs
        img_urls = []
        for element in driver.find_elements(By.XPATH, '//img[contains(@src, "media")]'):
            img_urls.append(element.get_attribute('src'))

        # Download media
        media_files = []
        for url in video_urls + img_urls:
            if not url: continue
            
            try:
                if 'video.twimg.com' in url:
                    # Use yt-dlp for Twitter videos
                    filename = f"video_{tweet_id}.mp4"
                    with YoutubeDL({'outtmpl': os.path.join(media_dir, filename)}) as ydl:
                        ydl.download([url])
                    media_files.append(filename)
                else:
                    # Download images
                    filename = f"image_{len(media_files)}.jpg"
                    with open(os.path.join(media_dir, filename), 'wb') as f:
                        f.write(requests.get(url).content)
                    media_files.append(filename)
            except Exception as e:
                print(f"Failed to download {url}: {str(e)}")

        # Save HTML
        with open(os.path.join(folder_name, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Tweet Archive</title>
                <style>
                    body {{ 
                        max-width: 600px;
                        margin: 0 auto;
                        padding: 20px;
                        font-family: system-ui, sans-serif;
                    }}
                    .tweet-media {{ 
                        width: 100%;
                        margin: 10px 0;
                        border-radius: 12px;
                    }}
                </style>
            </head>
            <body>
                <h2>@{username}</h2>
                <div class="content">
                    {driver.find_element(By.TAG_NAME, 'article').get_attribute('outerHTML')}
                </div>
                <div class="media">
                    {"".join(f'<video class="tweet-media" controls><source src="media/{file}"></video>' 
                            if file.startswith('video') else 
                            f'<img class="tweet-media" src="media/{file}">' 
                            for file in media_files)}
                </div>
            </body>
            </html>
            """)

        print(f"Successfully saved to: {folder_name}")

    finally:
        driver.quit()

if __name__ == "__main__":
    tweet_url = input("Enter Twitter/X URL: ")
    download_tweet(tweet_url)