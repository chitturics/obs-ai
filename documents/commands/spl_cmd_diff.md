---
 command: diff
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/diff
 title: diff
 download_date: 2026-02-03 09:04:53
---

 # diff

The diff command mimics *nix diff output and compares two search results at a time by returning the line-by-line difference, or comparison, of the two.  The two search results compared are specified by the two position values position1 and position2. These values default to 1 and 2 to compare the first two results.

By default, the text (_raw field) of the two search results is compared. Other fields can be compared by selecting another field using attribute.

diff [position1=int] [position2=int] [attribute=string] [diffheader=bool] [context=bool] [maxlen=int]

#### Optional arguments

#### Example 1:

Compare the "ip" values of the first and third search results.

#### Example 2:

Compare the 9th search results to the 10th.
 