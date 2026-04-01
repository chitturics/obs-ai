#!/usr/bin/env python3
"""
Generate an HTML index page for all feedback files.
This creates feedback/index.html that lists all feedback with Q&A, references, and ratings.
"""
import os
from pathlib import Path
from datetime import datetime
import re
import html

def extract_feedback_metadata(html_file: Path) -> dict:
    """Extract metadata from a feedback HTML file."""
    try:
        content = html_file.read_text(encoding='utf-8')

        # Extract basic info from filename
        # Format: {timestamp}_{message_id}_{username}.html
        parts = html_file.stem.split('_')
        timestamp = parts[0] if len(parts) > 0 else "unknown"
        message_id = parts[1] if len(parts) > 1 else "unknown"
        username = parts[2] if len(parts) > 2 else "unknown"

        # Extract value (thumbs up/down)
        value_match = re.search(r'<strong>Value:</strong>\s*(-?\d+)', content)
        value = int(value_match.group(1)) if value_match else 0

        # Extract question
        question_match = re.search(r'<h3>Question</h3>\s*<pre>(.*?)</pre>', content, re.DOTALL)
        question = question_match.group(1).strip() if question_match else "No question"

        # Extract answer
        answer_match = re.search(r'<h3>Answer</h3>\s*<pre>(.*?)</pre>', content, re.DOTALL)
        answer = answer_match.group(1).strip() if answer_match else "No answer"

        # Extract comment
        comment_match = re.search(r'<h3>Comment</h3>\s*<pre>(.*?)</pre>', content, re.DOTALL)
        comment = comment_match.group(1).strip() if comment_match else ""

        # Extract references from context (URLs)
        context_match = re.search(r'<h3>Context</h3>\s*<pre>(.*?)</pre>', content, re.DOTALL)
        context = context_match.group(1) if context_match else ""

        # Find URLs in context
        url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        urls = re.findall(url_pattern, context)

        # Find spec/conf file references
        spec_pattern = r'([a-zA-Z0-9_-]+\.(?:spec|conf))'
        specs = re.findall(spec_pattern, context + question + answer)

        return {
            'filename': html_file.name,
            'timestamp': timestamp,
            'message_id': message_id,
            'username': username,
            'value': value,
            'question': question[:200],  # First 200 chars
            'answer': answer[:300],  # First 300 chars
            'comment': comment[:200] if comment else "",
            'urls': list(set(urls))[:5],  # Top 5 unique URLs
            'specs': list(set(specs))[:5],  # Top 5 unique spec files
            'datetime': datetime.strptime(timestamp, '%Y%m%dT%H%M%SZ') if 'T' in timestamp else datetime.now()
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        print(f"Error parsing {html_file}: {e}")
        return None

def generate_index_html(feedback_dir: Path, output_file: Path):
    """Generate index.html for all feedback files."""

    # Find all feedback HTML files
    feedback_files = sorted(feedback_dir.glob('*.html'), reverse=True)  # Newest first

    # Extract metadata from each file
    feedback_items = []
    for f in feedback_files:
        if f.name == 'index.html':
            continue  # Skip the index itself
        metadata = extract_feedback_metadata(f)
        if metadata:
            feedback_items.append(metadata)

    # Count stats
    total_feedback = len(feedback_items)
    thumbs_up = sum(1 for item in feedback_items if item['value'] > 0)
    thumbs_down = sum(1 for item in feedback_items if item['value'] < 0)

    # Generate HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Feedback Index - Splunk Assistant</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            padding: 30px;
        }}

        header {{
            border-bottom: 3px solid #2196F3;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}

        h1 {{
            color: #1976D2;
            font-size: 2em;
            margin-bottom: 10px;
        }}

        .stats {{
            display: flex;
            gap: 20px;
            margin: 20px 0;
            flex-wrap: wrap;
        }}

        .stat {{
            background: #f8f9fa;
            padding: 15px 25px;
            border-radius: 6px;
            border-left: 4px solid #2196F3;
        }}

        .stat-label {{
            font-size: 0.85em;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .stat-value {{
            font-size: 1.8em;
            font-weight: bold;
            color: #1976D2;
            margin-top: 5px;
        }}

        .filters {{
            margin: 20px 0;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 6px;
        }}

        .filter-btn {{
            padding: 8px 16px;
            margin-right: 10px;
            border: 1px solid #ddd;
            background: white;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.3s;
        }}

        .filter-btn:hover {{
            background: #2196F3;
            color: white;
            border-color: #2196F3;
        }}

        .filter-btn.active {{
            background: #2196F3;
            color: white;
            border-color: #2196F3;
        }}

        .feedback-item {{
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            padding: 20px;
            margin-bottom: 20px;
            transition: box-shadow 0.3s;
        }}

        .feedback-item:hover {{
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}

        .feedback-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #e0e0e0;
        }}

        .feedback-meta {{
            display: flex;
            gap: 15px;
            font-size: 0.9em;
            color: #666;
        }}

        .thumbs-up {{
            color: #4CAF50;
            font-size: 1.5em;
        }}

        .thumbs-down {{
            color: #f44336;
            font-size: 1.5em;
        }}

        .question {{
            background: #f1f8ff;
            padding: 15px;
            border-left: 4px solid #2196F3;
            border-radius: 4px;
            margin-bottom: 15px;
        }}

        .question-label {{
            font-weight: bold;
            color: #1976D2;
            margin-bottom: 5px;
        }}

        .answer {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 15px;
        }}

        .answer-label {{
            font-weight: bold;
            color: #666;
            margin-bottom: 5px;
        }}

        .comment {{
            background: #fff3cd;
            padding: 10px 15px;
            border-left: 4px solid #ffc107;
            border-radius: 4px;
            margin-bottom: 15px;
            font-style: italic;
        }}

        .references {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 10px;
        }}

        .ref-tag {{
            padding: 4px 10px;
            background: #e3f2fd;
            border: 1px solid #2196F3;
            border-radius: 12px;
            font-size: 0.85em;
            color: #1976D2;
        }}

        .view-link {{
            display: inline-block;
            padding: 8px 16px;
            background: #2196F3;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 0.9em;
            transition: background 0.3s;
        }}

        .view-link:hover {{
            background: #1976D2;
        }}

        .empty-state {{
            text-align: center;
            padding: 60px 20px;
            color: #999;
        }}

        .empty-state-icon {{
            font-size: 4em;
            margin-bottom: 20px;
        }}

        @media (max-width: 768px) {{
            .container {{
                padding: 15px;
            }}

            .stats {{
                flex-direction: column;
            }}

            .feedback-header {{
                flex-direction: column;
                align-items: flex-start;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📝 Feedback Index</h1>
            <p>All user feedback for Splunk Assistant</p>

            <div class="stats">
                <div class="stat">
                    <div class="stat-label">Total Feedback</div>
                    <div class="stat-value">{total_feedback}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Thumbs Up</div>
                    <div class="stat-value" style="color: #4CAF50;">{thumbs_up}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Thumbs Down</div>
                    <div class="stat-value" style="color: #f44336;">{thumbs_down}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Satisfaction Rate</div>
                    <div class="stat-value">{int(thumbs_up / total_feedback * 100) if total_feedback > 0 else 0}%</div>
                </div>
            </div>
        </header>

        <div class="filters">
            <strong>Filter:</strong>
            <button class="filter-btn active" onclick="filterFeedback('all')">All</button>
            <button class="filter-btn" onclick="filterFeedback('positive')">👍 Positive</button>
            <button class="filter-btn" onclick="filterFeedback('negative')">👎 Negative</button>
            <button class="filter-btn" onclick="filterFeedback('comments')">💬 With Comments</button>
        </div>

        <div id="feedback-list">
"""

    # Add each feedback item
    for item in feedback_items:
        thumbs_icon = "👍" if item['value'] > 0 else "👎"
        thumbs_class = "thumbs-up" if item['value'] > 0 else "thumbs-down"
        value_text = "Positive" if item['value'] > 0 else "Negative"
        data_filter = f"positive {('comments' if item['comment'] else '')}"if item['value'] > 0 else f"negative {('comments' if item['comment'] else '')}"

        html_content += f"""
            <div class="feedback-item" data-filter="{data_filter}">
                <div class="feedback-header">
                    <span class="{thumbs_class}">{thumbs_icon} {value_text}</span>
                    <div class="feedback-meta">
                        <span>👤 {html.escape(item['username'])}</span>
                        <span>🕒 {item['datetime'].strftime('%Y-%m-%d %H:%M UTC')}</span>
                    </div>
                </div>

                <div class="question">
                    <div class="question-label">Question:</div>
                    <div>{html.escape(item['question'])}</div>
                </div>

                <div class="answer">
                    <div class="answer-label">Answer Preview:</div>
                    <div>{html.escape(item['answer'])}</div>
                </div>
"""

        if item['comment']:
            html_content += f"""
                <div class="comment">
                    💬 {html.escape(item['comment'])}
                </div>
"""

        # Add references
        if item['specs'] or item['urls']:
            html_content += """
                <div class="references">
                    <strong>References:</strong>
"""
            for spec in item['specs']:
                html_content += f"""
                    <span class="ref-tag">📄 {html.escape(spec)}</span>
"""
            for url in item['urls'][:3]:  # Show max 3 URLs
                url_display = url.split('/')[-1][:30]  # Show last path segment
                html_content += f"""
                    <span class="ref-tag">🔗 {html.escape(url_display)}</span>
"""
            html_content += """
                </div>
"""

        html_content += f"""
                <div style="margin-top: 15px;">
                    <a href="{item['filename']}" class="view-link" target="_blank">View Full Details</a>
                </div>
            </div>
"""

    if total_feedback == 0:
        html_content += """
            <div class="empty-state">
                <div class="empty-state-icon">📭</div>
                <h3>No Feedback Yet</h3>
                <p>Feedback will appear here as users provide ratings.</p>
            </div>
"""

    # Close HTML
    html_content += """
        </div>
    </div>

    <script>
        function filterFeedback(filter) {
            const items = document.querySelectorAll('.feedback-item');
            const buttons = document.querySelectorAll('.filter-btn');

            // Update button states
            buttons.forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');

            // Filter items
            items.forEach(item => {
                const itemFilter = item.getAttribute('data-filter');

                if (filter === 'all' || itemFilter.includes(filter)) {
                    item.style.display = 'block';
                } else {
                    item.style.display = 'none';
                }
            });
        }
    </script>
</body>
</html>
"""

    # Write index file
    output_file.write_text(html_content, encoding='utf-8')
    print(f"✅ Generated feedback index: {output_file}")
    print(f"   Total feedback items: {total_feedback}")
    print(f"   Thumbs up: {thumbs_up}")
    print(f"   Thumbs down: {thumbs_down}")

def main():
    """Main function."""
    feedback_dir = Path(os.getenv("FEEDBACK_PUBLIC_DIR", "/app/public/feedback"))

    if not feedback_dir.exists():
        feedback_dir.mkdir(parents=True, exist_ok=True)
        print(f"Created feedback directory: {feedback_dir}")

    output_file = feedback_dir / "index.html"

    generate_index_html(feedback_dir, output_file)

    docs_base = (os.getenv("DOCS_BASE_URL") or "/public").rstrip("/")
    if not docs_base.startswith(("http://", "https://", "/")):
        docs_base = f"/{docs_base}"
    print(f"\n🌐 Access feedback index at: {docs_base}/feedback/")

if __name__ == "__main__":
    main()
