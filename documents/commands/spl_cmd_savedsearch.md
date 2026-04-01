---
 command: savedsearch
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/savedsearch
 title: savedsearch
 download_date: 2026-02-03 09:16:02
---

 # savedsearch

Runs a saved search, or report, and returns the search results of a saved search.
If the search contains replacement placeholder terms, such as $replace_me$, the search processor replaces the placeholders with the strings you specify. For example:

| savedsearch <savedsearch_name> [<savedsearch-options>...]

#### Required arguments

#### Optional arguments

The savedsearch command is a generating command  and must start with a leading pipe character.

The savedsearch command always runs a new search. To reanimate the results of a previously run search, use the loadjob command.

When the savedsearch command runs a saved search, the command always applies the permissions associated with the role of the person running the savedsearch command to the search. The savedsearch command never applies the permissions associated with the role of the person who created and owns the search to the search. This happens even when a saved search has been set up to run as the report owner.

See Determine whether to run reports as the report owner or user in the Reporting Manual.

#### Time ranges

- If you specify All Time in the time range picker, the savedsearch  command uses the time range that was saved with the saved search.

- If you specify any other time in the time range picker, the time range that you specify overrides the time range that was saved with the saved search.

#### Example 1

Run the saved search "mysecurityquery".

#### Example2

Run the saved search "mysearch". Where the replacement placeholder term $replace_me$ appears in the saved search, use "value" instead.

search, loadjob
 