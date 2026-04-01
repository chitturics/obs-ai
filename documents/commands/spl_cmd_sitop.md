---
 command: sitop
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/sitop
 title: sitop
 download_date: 2026-02-03 09:17:32
---

 # sitop

Summary indexing is a method you can use to speed up long-running searches that do not qualify for report acceleration, such as searches that use commands that are not streamable before the reporting command. For more information, see Overview of summary-based search acceleration and Use summary indexing for increased reporting efficiency in the Knowledge Manager Manual.

The sitop command is the summary indexing version of the top command, which returns the most frequent value of a field or combination of fields. The sitop command populates a summary index with the statistics necessary to generate a top report. After you populate the summary index, use the regular top command with the exact same search string as the sitop command search to report against it.

sitop [<N>] [<top-options>...] <field-list> [<by-clause>]

Note: This is the exact same syntax as that of the top command.

#### Required arguments

#### Optional arguments

#### Top options

#### Example 1:

Compute the necessary information to later do 'top foo bar' on summary indexed results.

#### Example 2:

Populate a summary index with the top source IP addresses in a scheduled search that runs daily:

Save the search as, "Summary - firewall top src_ip".

Later, when you want to retrieve that information and report on it, run this search over the past year:

Additionally, because this search specifies the search name, it filters out other data that have been placed in the summary index by other summary indexing searches.

collect, overlap, sichart, sirare, sistats, sitimechart
 