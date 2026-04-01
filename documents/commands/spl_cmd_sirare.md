---
 command: sirare
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/sirare
 title: sirare
 download_date: 2026-02-03 09:17:14
---

 # sirare

Summary indexing is a method you can use to speed up long-running searches that do not qualify for report acceleration, such as searches that use commands that are not streamable before the reporting command. For more information, see "About report accelleration and summary indexing" and "Use summary indexing for increased reporting efficiency" in the Knowledge Manager Manual.

The sirare command is the summary indexing version of the rare command, which returns the least common values of a field or combination of fields. The sirare command populates a summary index with the statistics necessary to generate a rare report. After you populate the summary index, use the regular rare command with the exact same search string as the rare command search to report against it.

sirare [<top-options>...] <field-list> [<by-clause>]

#### Required arguments

#### Optional arguments

#### Top options

#### Example 1:

Compute the necessary information to later do 'rare foo bar' on summary indexed results.

collect, overlap, sichart, sistats, sitimechart, sitop
 