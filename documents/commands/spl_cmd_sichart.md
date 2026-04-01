---
 command: sichart
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/sichart
 title: sichart
 download_date: 2026-02-03 09:17:09
---

 # sichart

Summary indexing is a method you can use to speed up long-running searches that do not qualify for report acceleration, such as searches that use commands that are not streamable before the reporting command. For more information, see "About report accelleration and summary indexing" and "Use summary indexing for increased reporting efficiency" in the Knowledge Manager Manual.

The summary indexing version of the chart command.  The sichart command populates a summary index with the statistics necessary to generate a chart visualization.  For example, it can create a column, line, area, or pie chart. After you populate the summary index, you can use the chart command with the exact same search that you used with the sichart command to search against the summary index.

Required syntax is in bold.

For syntax descriptions, refer to the chart command.

#### Supported functions

You can use a wide range of functions with the sichart command. For general information about using functions, see  Statistical and charting functions.

#### Example 1:

Compute the necessary information to later do 'chart avg(foo) by bar' on summary indexed results.

chart,
collect, overlap, sirare, sistats, sitimechart, sitop
 