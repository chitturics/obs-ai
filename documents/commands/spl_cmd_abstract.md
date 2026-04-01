---
 command: abstract
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/abstract
 title: Search Commands
 download_date: 2026-02-03 09:00:58
---

 # abstract

Produces an abstract, a summary or brief representation, of the text of the search results. The original text is replaced by the summary.

The abstract is produced by a scoring mechanism.  Events that are larger than the selected maxlines, those with more textual terms and more terms on adjacent lines, are preferred over events with fewer terms.  If a line has a search term, its neighboring lines also partially match, and might be returned to provide context. When there are gaps between the selected lines, lines are prefixed with an ellipsis (...).

If the text of an event has fewer lines or an equal number of lines as maxlines, no change occurs.

The required syntax is in bold.

#### Optional arguments

#### Specify the number of lines to return

Show a summary of up to 5 lines for each search result.

#### Specify the number of terms to return

Consider the following events:

| Time | Event |
| --- | --- |
| 1/4/23 
6:22:16.000 PM | 91.205.189.15 - - [04/Jan/2023:18:22:16] "GET /oldlink?itemId=EST-14&JSESSIONID=SD6SL7FF7ADFF53113 HTTP 1.1" 200 1665 "http://www.buttercupgames.com/oldlink?itemId=EST-14" "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/536.5 (KHTML, like Gecko) Chrome/19.0.1084.46 Safari/536.5" 159 |
| 1/3/23
11:08:57.000 PM | 194.146.236.22 - - [03/Jan/2023:23:08:57] "POST /cart.do?action=addtocart&itemId=EST-15&productId=WC-SH-T02&JSESSIONID=SD4SL1FF2ADFF47548 HTTP 1.1" 200 1493 "http://www.buttercupgames.com/product.screen?productId=WC-SH-T02" "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/536.5 (KHTML, like Gecko) Chrome/19.0.1084.52 Safari/536.5" 848 |

If you specify maxterms=20 the results look like this:

| Time | Event |
| --- | --- |
| 1/4/23 
6:22:16.000 PM | 91.205.189.15 - - [04/Jan/2023:18 |
| 1/3/23
11:08:57.000 PM | 194.146.236.22  - - [03/Jan/2023:23 |

The "terms" are identified as shown in the following table:

| Number | Event 1 term | Event 2 term |
| --- | --- | --- |
| 1 | 91 | 194 |
| 2 | . | . |
| 3 | 205 | 146 |
| 4 | . | . |
| 5 | 189 | 236 |
| 6 | . | . |
| 7 | 15 | 22 |
| 8 |  |  |
| 9 | - | - |
| 10 |  |  |
| 11 | - | - |
| 12 |  |  |
| 13 | [ | [ |
| 14 | 04 | 03 |
| 15 | / | / |
| 16 | Jan | Jan |
| 17 | / | / |
| 18 | 2023 | 2023 |
| 19 | : | : |
| 20 | 18 | 23 |
 