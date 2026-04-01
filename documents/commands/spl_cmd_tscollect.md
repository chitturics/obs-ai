---
 command: tscollect
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/tscollect
 title: tscollect
 download_date: 2026-02-03 09:20:12
---

 # tscollect

| This feature is deprecated. |
| --- |
| The tscollect command is deprecated in the Splunk platform as of version 7.3.0. Although this command continues to function, it might be removed in a future version. This command has been superseded by data models. See Accelerate data models in the Knowledge Manager Manual.

In the version 7.3.0 Release Notes, see Deprecated features. |

The tscollect command uses indexed fields to create time series index (tsidx) files in a namespace that you define. The result tables in these files are a subset of the data that you have already indexed. This then enables you to use the tstats command to search and report on these tsidx files instead of searching raw data. Because you are searching on a subset of the full index, the search should complete faster than it would otherwise.

The tscollect command creates multiple tsidx files in the same namespace. The command will begin a new tsidx file when it determines that the tsidx file it is currently creating has gotten big enough.

Only users with the indexes_edit capability can run this command. See Usage.

CAUTION: This command is considered risky because, if used incorrectly, it can pose a security risk or potentially lose data when it runs. As a result, this command triggers SPL safeguards. See SPL safeguards for risky commands in Securing the Splunk Platform.

... | tscollect [namespace=<string>] [squashcase=<bool>] [keepresults=<bool>]

#### Optional arguments

You must have the indexes_edit capability to run the tscollect command. By default, the admin role has this capability and the user and power roles do not have this capability.

Example 1: Write the results table to tsidx files in namespace foo.

Example 2: Retrieve events from the main index and write the values of field foo to tsidx files in the job directory.

collect, stats, tstats
 