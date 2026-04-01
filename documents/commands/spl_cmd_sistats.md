---
 command: sistats
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/sistats
 title: sistats
 download_date: 2026-02-03 09:17:20
---

 # sistats

The sistats command is one of several commands that you can use to create summary indexes.  Summary indexing is one of the methods that you can use to speed up searches that take a long time to run.

The sistats command is the summary indexing version of the stats command, which calculates aggregate statistics over the dataset.

The sistats command populates a summary index. You must then create a report to generate the summary statistics.  See the Usage section.

sistats [allnum=<bool>] [delim=<string>] ( <stats-agg-term> | <sparkline-agg-term> ) [<by clause>]

- For descriptions of each of the arguments in this syntax, refer to the stats command.
- For information about functions that you can use with the sistats command, see  Statistical and charting functions.

The summary indexes exist separately from your main indexes.

After you create the summary index, create a report by running a search against the summary index.  You use the exact same search string that you used to populate the summary index, substituting the  stats command for the sistats command, to create your reports.

For more information, see About report acceleration and summary indexing and Use summary indexing for increased reporting efficiency in the Knowledge Manager Manual.

#### Statistical functions that are not applied to specific fields

With the exception of the count function, when you pair the sistats command with functions that are not applied to specific fields or eval expressions that resolve into fields, the search head processes it as if it were applied to a wildcard for all fields. In other words, when you have | sistats avg in a search, it returns results for | sistats avg(*).

This "implicit wildcard" syntax is officially deprecated, however. Make the wildcard explicit. Write | sistats <function>(*) when you want a function to apply to all possible fields.

#### Memory and sistats search performance

A pair of limits.conf settings strike a balance between the performance of sistats searches and the amount of memory they use during the search process, in RAM and on disk. If your sistats searches are consistently slow to complete you can adjust these settings to improve their performance, but at the cost of increased search-time memory usage, which can lead to search failures.

If you have Splunk Cloud Platform, you need to file a Support ticket to change these settings.

For more information, see Memory and stats search performance in the Search Manual.

#### Example 1:

Create a summary index with the statistics about the average, for each hour, of any unique field that ends with the string "lay". For example, delay, xdelay, relay, etc.

To create a report, run a search against the summary index using this search

collect, overlap, sichart, sirare, sitop, sitimechart

For a detailed explanation and examples of summary indexing, see  Use summary indexing for increased reporting efficiency in the Knowledge Manager Manual.
 