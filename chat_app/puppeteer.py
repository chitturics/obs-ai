"""
Web scraper using Playwright (Python) - No Node.js required!
Blocks heavy resources, removes noisy elements, and returns cleaned content.

Install:
    pip install playwright
    playwright install chromium
"""
import os
from typing import Tuple, Optional, Dict
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


def fetch_with_playwright(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout_ms: int = 60000  # Increased timeout
) -> Tuple[str, str]:
    """
    Fetch URL using Playwright (pure Python, no Node.js needed)
    
    Args:
        url: URL to fetch
        headers: Optional HTTP headers dict
        timeout_ms: Timeout in milliseconds
        
    Returns:
        Tuple of (content_type, html_content)
    """
    ua = os.getenv(
        "PLAYWRIGHT_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )

    try:
        with sync_playwright() as p:
            # Launch browser
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled'
                ]
            )

            # Create context with custom settings
            context = browser.new_context(
                user_agent=ua,
                viewport={'width': 1920, 'height': 1080},
                extra_http_headers=headers or {}
            )

            # Anti-detection measures
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => false});
                window.chrome = {runtime: {}};
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            """)

            page = context.new_page()

            # Block heavy resources
            page.route("**/*", lambda route: (
                route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"]
                else route.continue_()
            ))

            # Navigate to URL
            response = page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)

            if not response:
                raise RuntimeError("No response received from server")

            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}: {response.status_text}")

            # Wait for body
            try:
                page.wait_for_selector('body', timeout=5000)
            except PlaywrightTimeout:
                pass  # Continue even if body not found

            # Remove unwanted elements
            remove_selectors = [
                'script', 'style', 'nav', 'footer', 'header', 'iframe',
                'noscript', 'aside', '.ads', '.advertisement', '[class*="cookie"]',
                '[id*="cookie"]', '[class*="banner"]'
            ]

            for selector in remove_selectors:
                page.evaluate(f"""
                    document.querySelectorAll('{selector}').forEach(el => el.remove());
                """)

            # Get content type
            content_type = response.headers.get('content-type', 'text/html').split(';')[0]

            # Get HTML content
            html = page.content()

            browser.close()

            return content_type, html

    except PlaywrightTimeout:
        raise RuntimeError(f"Request timeout after {timeout_ms}ms")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        raise RuntimeError(f"Playwright fetch failed: {str(e)}")


def fetch_with_selenium(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout_sec: int = 30
) -> Tuple[str, str]:
    """
    Fetch URL using Selenium (alternative option)
    
    Install:
        pip install selenium webdriver-manager
    
    Args:
        url: URL to fetch
        headers: Optional HTTP headers dict (limited support)
        timeout_sec: Timeout in seconds
        
    Returns:
        Tuple of (content_type, html_content)
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        raise RuntimeError(
            "Selenium not installed. Run: pip install selenium webdriver-manager"
        )

    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # Block images for faster loading
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2
    }
    chrome_options.add_experimental_option("prefs", prefs)

    ua = os.getenv(
        "PLAYWRIGHT_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    chrome_options.add_argument(f'user-agent={ua}')

    driver = None
    try:
        # Auto-download and setup ChromeDriver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(timeout_sec)

        # Anti-detection
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {get: () => false});
                window.chrome = {runtime: {}};
            '''
        })

        # Navigate
        driver.get(url)

        # Wait for body
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            pass  # optional module

        # Remove unwanted elements
        remove_script = """
        var selectors = [
            'script', 'style', 'nav', 'footer', 'header', 'iframe',
            'noscript', 'aside', '.ads', '.advertisement'
        ];
        selectors.forEach(function(sel) {
            var elements = document.querySelectorAll(sel);
            elements.forEach(function(el) { el.remove(); });
        });
        """
        driver.execute_script(remove_script)

        # Get HTML
        html = driver.page_source

        return 'text/html', html

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        raise RuntimeError(f"Selenium fetch failed: {str(e)}")
    finally:
        if driver:
            driver.quit()


def fetch_with_requests_html(url: str, timeout_sec: int = 30) -> Tuple[str, str]:
    """
    Fetch URL using requests-html (lightweight, uses Chromium internally)
    
    Install:
        pip install requests-html
        # First run will auto-download Chromium
    
    Args:
        url: URL to fetch
        timeout_sec: Timeout in seconds
        
    Returns:
        Tuple of (content_type, html_content)
    """
    try:
        from requests_html import HTMLSession
    except ImportError:
        raise RuntimeError("requests-html not installed. Run: pip install requests-html")

    try:
        session = HTMLSession()
        response = session.get(url, timeout=timeout_sec)

        # Render JavaScript
        response.html.render(timeout=timeout_sec)

        # Get rendered HTML
        html = response.html.html
        content_type = response.headers.get('content-type', 'text/html').split(';')[0]

        return content_type, html

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        raise RuntimeError(f"requests-html fetch failed: {str(e)}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python scraper.py <url> [method]")
        print("Methods: playwright (default), selenium, requests-html")
        print("\nExamples:")
        print("  python scraper.py https://example.com")
        print("  python scraper.py https://example.com selenium")
        sys.exit(1)

    url = sys.argv[1]
    method = sys.argv[2] if len(sys.argv) > 2 else "playwright"

    print(f"Fetching: {url}")
    print(f"Method: {method}")
    print("-" * 60)

    try:
        if method == "playwright":
            print("Using Playwright (recommended)...")
            ctype, html = fetch_with_playwright(url)
        elif method == "selenium":
            print("Using Selenium...")
            ctype, html = fetch_with_selenium(url)
        elif method == "requests-html":
            print("Using requests-html...")
            ctype, html = fetch_with_requests_html(url)
        else:
            print(f"Unknown method: {method}")
            sys.exit(1)

        print("✓ Success!")
        print(f"Content-Type: {ctype}")
        print(f"HTML Length: {len(html)} characters")
        print("-" * 60)
        print("Preview (first 1000 chars):")
        print(html[:1000])
        print("...")

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        print(f"✗ Error: {exc}")
        sys.exit(1)
