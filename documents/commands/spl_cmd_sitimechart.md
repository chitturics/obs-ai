---
 command: sitimechart
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/sitimechart
 title: sitimechart
 download_date: 2026-02-03 09:17:25
---

 # sitimechart

Summary indexing is a method you can use to speed up long-running searches that do not qualify for report acceleration, such as searches that use commands that are not streamable before the transforming command. For more information, see "About report accelleration and summary indexing" and "Use summary indexing for increased reporting efficiency" in the Knowledge Manager Manual.

The sitimechart command is the summary indexing version of the timechart command, which creates a time-series chart visualization with a corresponding table of statistics. The sitimechart command populates a summary index with the statistics necessary to generate a timechart report. After you use an sitimechart search to populate the summary index, use the regular timechart command with the exact same search string as the sitimechart search to report against the summary index.

The required syntax is in bold.

When specifying sitimechart command arguments, either <single-agg> or <eval-expression> BY <split-by-clause> is required.

For descriptions of each of these arguments, see the timechart command.

#### Supported functions

You can use a wide range of functions with the sitimechart command. For general information about using functions, see  Statistical and charting functions.

#### Example 1:

Use the collect command to populate a summary index called mysummary with the statistics about CPU usage organized by host,

Note: The collect command adds the results of a search to a summary index that you specify. You must create the summary index before you invoke the collect command.

Then use the timechart command with the same search to generate a timechart report.

collect, overlap, sichart, sirare, sistats, sitop
 