---
 command: overlap
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/overlap
 title: overlap
 download_date: 2026-02-03 09:13:39
---

 # overlap

Find events in a summary index that overlap in time, or find gaps in time during which a scheduled saved search might have missed events.

- If you find a gap, run the search over the period of the gap and summary index the results using "| collect".
- If you find overlapping events, manually delete the overlaps from the summary index by using the search language.

The overlap command invokes an external python script  $SPLUNK_HOME/etc/apps/search/bin/sumindexoverlap.py. The script expects input events from the summary index and finds any time overlaps and gaps between events with the same 'info_search_name' but different 'info_search_id'.

Important: Input events are expected to have the following fields: 'info_min_time', 'info_max_time' (inclusive and exclusive, respectively) , 'info_search_id' and 'info_search_name' fields. If the index contains raw events (_raw), the overlap command does not work. Instead, the index should contain events such as chart, stats, and timechart results.

#### Example 1:

Find overlapping events in the "summary" index.

collect, sistats, sitop, sirare, sichart, sitimechart
 