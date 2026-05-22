"""
URL content processing service with YouTube transcript support.

This module handles URL processing, web scraping, and YouTube transcript extraction
with a clean, standard design.
"""

import logging
import re
import time
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
from langchain.schema import Document

# Web scraping
import requests
from bs4 import BeautifulSoup

# Browser automation
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# YouTube transcript
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    YOUTUBE_TRANSCRIPT_AVAILABLE = True
except ImportError:
    YOUTUBE_TRANSCRIPT_AVAILABLE = False
    logging.warning("youtube-transcript-api not available. Install with: pip install youtube-transcript-api")

# Configure logging
logger = logging.getLogger(__name__)

class UrlContentService:
    """Service for processing URLs and extracting content."""
    
    def __init__(self):
        """Initialize the URL content service."""
        self.driver = None
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        self.max_pages_per_site = 5
        self.max_content_length = 100000  # 100KB limit per URL
        logger.info("URL content service initialized")
    
    def process_urls(self, urls: List[str], user_session: str) -> Dict[str, Any]:
        """
        Process a list of URLs and extract content.
        
        Args:
            urls: List of URL strings to process
            user_session: User session identifier
            
        Returns:
            Dict with processing results
        """
        if not urls:
            return {
                "success": True,
                "urls_processed": 0,
                "urls_successful": 0,
                "url_documents": [],
                "url_details": []
            }
        
        logger.info(f"Processing {len(urls)} URLs")
        
        url_documents = []
        url_details = []
        successful_urls = 0
        
        for i, url in enumerate(urls):
            try:
                # Validate and normalize URL
                normalized_url = self._normalize_url(url)
                if not normalized_url:
                    url_details.append({
                        'url': url,
                        'success': False,
                        'error': 'Invalid URL format'
                    })
                    continue
                
                # Check if it's a YouTube URL
                if self._is_youtube_url(normalized_url):
                    result = self._process_youtube_url(normalized_url, i)
                else:
                    result = self._process_web_url(normalized_url, i)
                
                if result['success']:
                    # Create Document objects
                    documents = self._create_documents_from_content(
                        result['content'], 
                        result['title'], 
                        normalized_url, 
                        result.get('metadata', {})
                    )
                    
                    url_documents.extend(documents)
                    successful_urls += 1
                    
                    url_details.append({
                        'url': normalized_url,
                        'success': True,
                        'title': result['title'],
                        'content_length': len(result['content']),
                        'documents_created': len(documents),
                        'extraction_method': result.get('extraction_method', 'unknown')
                    })
                else:
                    url_details.append({
                        'url': normalized_url,
                        'success': False,
                        'error': result['error']
                    })
                    
            except Exception as e:
                logger.error(f"Error processing URL {url}: {e}")
                url_details.append({
                    'url': url,
                    'success': False,
                    'error': f"Processing error: {str(e)}"
                })
        
        # Clean up browser resources
        self._cleanup_driver()
        
        return {
            "success": True,
            "urls_processed": len(urls),
            "urls_successful": successful_urls,
            "url_documents": url_documents,
            "url_details": url_details
        }
    
    def _normalize_url(self, url: str) -> Optional[str]:
        """
        Normalize and validate URL.
        
        Args:
            url: Raw URL string
            
        Returns:
            Normalized URL or None if invalid
        """
        if not url or not isinstance(url, str):
            return None
        
        url = url.strip()
        
        # Add scheme if missing
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Basic URL validation
        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                return None
            return url
        except Exception:
            return None
    
    def _is_youtube_url(self, url: str) -> bool:
        """
        Check if URL is a YouTube video URL.
        
        Args:
            url: URL to check
            
        Returns:
            True if YouTube URL, False otherwise
        """
        youtube_domains = ['youtube.com', 'youtu.be', 'm.youtube.com', 'www.youtube.com']
        parsed = urlparse(url)
        
        if parsed.netloc.lower() in youtube_domains:
            # Check for video patterns
            if '/watch' in parsed.path or '/v/' in parsed.path or parsed.netloc == 'youtu.be':
                return True
        
        return False
    
    def _extract_youtube_video_id(self, url: str) -> Optional[str]:
        """
        Extract YouTube video ID from URL.
        
        Args:
            url: YouTube URL
            
        Returns:
            Video ID or None if not found
        """
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'(?:embed\/)([0-9A-Za-z_-]{11})',
            r'(?:v\/)([0-9A-Za-z_-]{11})',
            r'(?:\/watch\?v=)([0-9A-Za-z_-]{11})',
            r'(?:\/embed\/)([0-9A-Za-z_-]{11})',
            r'(?:\/v\/)([0-9A-Za-z_-]{11})',
            r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None
    
    def _process_youtube_url(self, url: str, index: int) -> Dict[str, Any]:
        """
        Process YouTube URL to extract transcript and metadata.
        
        Args:
            url: YouTube URL
            index: URL index for identification
            
        Returns:
            Processing result dictionary
        """
        if not YOUTUBE_TRANSCRIPT_AVAILABLE:
            return {
                'success': False,
                'error': 'YouTube transcript API not available'
            }
        
        try:
            # Extract video ID
            video_id = self._extract_youtube_video_id(url)
            if not video_id:
                return {
                    'success': False,
                    'error': 'Could not extract YouTube video ID'
                }
            
            # Get transcript
            try:
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
                transcript_text = ' '.join([entry['text'] for entry in transcript_list])
            except Exception as e:
                logger.warning(f"Could not get transcript for {video_id}: {e}")
                # Fallback to description scraping
                return self._fallback_youtube_scraping(url, video_id)
            
            # Get video metadata using web scraping
            metadata = self._get_youtube_metadata(url, video_id)
            
            # Combine transcript and metadata
            content = self._format_youtube_content(transcript_text, metadata)
            
            return {
                'success': True,
                'content': content,
                'title': metadata.get('title', f'YouTube Video {video_id}'),
                'extraction_method': 'youtube_transcript_api',
                'metadata': {
                    **metadata,
                    'video_id': video_id,
                    'transcript_length': len(transcript_text),
                    'url': url
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing YouTube URL {url}: {e}")
            return {
                'success': False,
                'error': f"YouTube processing failed: {str(e)}"
            }
    
    def _get_youtube_metadata(self, url: str, video_id: str) -> Dict[str, Any]:
        """
        Get YouTube video metadata using web scraping.
        
        Args:
            url: YouTube URL
            video_id: Video ID
            
        Returns:
            Metadata dictionary
        """
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            metadata = {'video_id': video_id}
            
            # Extract title
            title_tag = soup.find('meta', property='og:title')
            if title_tag:
                metadata['title'] = title_tag.get('content', '')
            
            # Extract description
            desc_tag = soup.find('meta', property='og:description')
            if desc_tag:
                metadata['description'] = desc_tag.get('content', '')
            
            # Extract duration
            duration_tag = soup.find('meta', itemprop='duration')
            if duration_tag:
                metadata['duration'] = duration_tag.get('content', '')
            
            # Extract channel name
            channel_tag = soup.find('link', itemprop='name')
            if channel_tag:
                metadata['channel'] = channel_tag.get('content', '')
            
            # Extract view count (if available)
            views_tag = soup.find('meta', itemprop='interactionCount')
            if views_tag:
                metadata['view_count'] = views_tag.get('content', '')
            
            return metadata
            
        except Exception as e:
            logger.warning(f"Could not get YouTube metadata for {video_id}: {e}")
            return {'video_id': video_id}
    
    def _fallback_youtube_scraping(self, url: str, video_id: str) -> Dict[str, Any]:
        """
        Fallback method for YouTube when transcript API fails.
        
        Args:
            url: YouTube URL
            video_id: Video ID
            
        Returns:
            Processing result dictionary
        """
        try:
            metadata = self._get_youtube_metadata(url, video_id)
            
            # Use description as content if available
            content = metadata.get('description', '')
            if not content:
                content = f"YouTube video: {metadata.get('title', video_id)}"
            
            return {
                'success': True,
                'content': content,
                'title': metadata.get('title', f'YouTube Video {video_id}'),
                'extraction_method': 'youtube_fallback_scraping',
                'metadata': metadata
            }
            
        except Exception as e:
            logger.error(f"YouTube fallback scraping failed for {url}: {e}")
            return {
                'success': False,
                'error': f"YouTube fallback failed: {str(e)}"
            }
    
    def _format_youtube_content(self, transcript: str, metadata: Dict[str, Any]) -> str:
        """
        Format YouTube content with metadata and transcript.
        
        Args:
            transcript: Video transcript text
            metadata: Video metadata
            
        Returns:
            Formatted content string
        """
        content_parts = []
        
        # Add metadata
        content_parts.append("=== YouTube Video ===")
        if metadata.get('title'):
            content_parts.append(f"Title: {metadata['title']}")
        if metadata.get('channel'):
            content_parts.append(f"Channel: {metadata['channel']}")
        if metadata.get('duration'):
            content_parts.append(f"Duration: {metadata['duration']}")
        if metadata.get('description'):
            content_parts.append(f"Description: {metadata['description']}")
        
        content_parts.append("\n=== Transcript ===")
        content_parts.append(transcript)
        
        return "\n".join(content_parts)
    
    def _process_web_url(self, url: str, index: int) -> Dict[str, Any]:
        """
        Process regular web URL with crawling capabilities.
        
        Args:
            url: Web URL
            index: URL index for identification
            
        Returns:
            Processing result dictionary
        """
        try:
            # Try static scraping first
            soup = self._try_static_scrape(url)
            used_selenium = False
            
            # Fallback to Selenium if needed
            if soup is None or len(soup.get_text(strip=True)) < 200:
                soup = self._try_dynamic_scrape(url)
                used_selenium = True
            
            if soup is None:
                return {
                    'success': False,
                    'error': 'Could not extract content from URL'
                }
            
            # Extract and clean content
            title, content = self._extract_web_content(soup, url)
            
            if not content or len(content.strip()) < 50:
                return {
                    'success': False,
                    'error': 'No meaningful content extracted'
                }
            
            # Limit content length
            if len(content) > self.max_content_length:
                content = content[:self.max_content_length] + "..."
            
            return {
                'success': True,
                'content': content,
                'title': title,
                'extraction_method': 'selenium' if used_selenium else 'static',
                'metadata': {
                    'url': url,
                    'used_selenium': used_selenium,
                    'content_length': len(content)
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing web URL {url}: {e}")
            return {
                'success': False,
                'error': f"Web scraping failed: {str(e)}"
            }
    
    def _try_static_scrape(self, url: str) -> Optional[BeautifulSoup]:
        """Try static scraping with requests."""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            logger.debug(f"Static scraping failed for {url}: {e}")
            return None
    
    def _try_dynamic_scrape(self, url: str) -> Optional[BeautifulSoup]:
        """Try dynamic scraping with Selenium."""
        try:
            driver = self._get_webdriver()
            if driver is None:
                return None
            
            driver.get(url)
            
            # Wait for content to load
            time.sleep(3)
            
            return BeautifulSoup(driver.page_source, 'html.parser')
            
        except Exception as e:
            logger.debug(f"Dynamic scraping failed for {url}: {e}")
            return None
    
    def _get_webdriver(self):
        """Get or create Chrome WebDriver instance."""
        if self.driver is None:
            try:
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--window-size=1920,1080")
                chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                chrome_options.add_argument("--disable-blink-features=AutomationControlled")
                chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
                chrome_options.add_experimental_option('useAutomationExtension', False)
                
                self.driver = webdriver.Chrome(
                    service=Service(ChromeDriverManager().install()), 
                    options=chrome_options
                )
                self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                self.driver.implicitly_wait(10)
                
            except Exception as e:
                logger.warning(f"Could not initialize WebDriver: {e}")
                self.driver = None
        
        return self.driver
    
    def _cleanup_driver(self):
        """Clean up WebDriver instance."""
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None
            except Exception as e:
                logger.warning(f"Error cleaning up WebDriver: {e}")
    
    def _extract_web_content(self, soup: BeautifulSoup, url: str) -> tuple[str, str]:
        """
        Extract title and content from BeautifulSoup object.
        
        Args:
            soup: BeautifulSoup object
            url: Original URL
            
        Returns:
            Tuple of (title, content)
        """
        # Extract title
        title = "Web Page"
        if soup.title:
            title = soup.title.string.strip() if soup.title.string else title
        
        # Remove unwanted elements
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            element.decompose()
        
        # Try to find main content
        content_selectors = [
            'main', 'article', '[role="main"]',
            '.content', '.main-content', '.post-content',
            '#content', '#main', 'body'
        ]
        
        main_content = None
        for selector in content_selectors:
            main_content = soup.select_one(selector)
            if main_content:
                break
        
        # Extract text content
        if main_content:
            text_content = main_content.get_text(separator='\n', strip=True)
        else:
            text_content = soup.get_text(separator='\n', strip=True)
        
        # Clean and filter content
        lines = text_content.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            if (line and len(line) > 3 and 
                not line.lower() in ['home', 'about', 'contact', 'menu', 'search', 'login', 'logout'] and
                not line.startswith(('©', '®', '™')) and
                len(line.split()) > 1):
                cleaned_lines.append(line)
        
        content = '\n'.join(cleaned_lines)
        
        return title, content
    
    def _create_documents_from_content(self, content: str, title: str, 
                                     url: str, metadata: Dict[str, Any]) -> List[Document]:
        """
        Create Document objects from extracted content.
        
        Args:
            content: Extracted content
            title: Content title
            url: Source URL
            metadata: Additional metadata
            
        Returns:
            List of Document objects
        """
        # For now, create a single document per URL
        # Could be enhanced to split long content into chunks
        
        # Enhanced content with metadata
        enhanced_content = f"URL: {url}\nTitle: {title}\n\n{content}"
        
        doc = Document(
            page_content=enhanced_content,
            metadata={
                'source': url,
                'filename': f"url_content_{hash(url) % 10000}.txt",
                'title': title,
                'page': 0,  # URLs are treated as single page documents
                'url': url,
                'extraction_method': metadata.get('extraction_method', 'unknown'),
                **metadata
            }
        )
        
        return [doc]
    
    def __del__(self):
        """Destructor to ensure WebDriver cleanup."""
        self._cleanup_driver()

# Singleton instance
_url_content_service = None

def get_url_content_service() -> UrlContentService:
    """Get the URL content service singleton instance."""
    global _url_content_service
    if _url_content_service is None:
        _url_content_service = UrlContentService()
    return _url_content_service