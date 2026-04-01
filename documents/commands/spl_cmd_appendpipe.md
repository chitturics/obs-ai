---
 command: appendpipe
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/appendpipe
 title: appendpipe
 download_date: 2026-02-03 09:02:12
---

 # appendpipe

Appends the result of the subpipeline to the search results.  Unlike a subsearch, the subpipeline is not run first. The subpipeline is run when the search reaches the appendpipe command. The appendpipe command is used to append the output of transforming commands, such as chart, timechart, stats, and top.

appendpipe [run_in_preview=<bool>] [<subpipeline>]

#### Optional Arguments

The appendpipe command can be useful because it provides a summary, total, or otherwise descriptive row of the entire dataset when you are constructing a table or chart. This command is also useful when you need the original results for additional calculations.

#### Example 1:

Append subtotals for each action across all users.

index=_audit | stats count by action user | appendpipe [stats sum(count) as count by action | eval user = "TOTAL - ALL USERS"] | sort action

The results appear on the Statistics tab and look something like this:

| action | user | count |
| --- | --- | --- |
| accelerate_search | admin | 209 |
| accelerate_search | buttercup | 345 |
| accelerate_search | can-delete | 6 |
| accelerate_search | TOTAL - ALL USERS | 560 |
| add | n/a | 1 |
| add | TOTAL - ALL USERS | 1 |
| change_authentication | admin | 50 |
| change_authentication | buttercup | 9 |
| change_authentication | can-delete | 24 |
| change_authentication | TOTAL - ALL USERS | 83 |

append, appendcols, join, set
 