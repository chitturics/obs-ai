---
 command: bucketdir
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/bucketdir
 title: bucketdir
 download_date: 2026-02-03 09:02:52
---

 # bucketdir

Replaces a field value with higher-level grouping, such as replacing filenames with directories.

Returns the maxcount events, by taking the incoming events and rolling up multiple sources into directories, by preferring directories that have many files but few events.  The field with the path is PATHFIELD (e.g., source), and strings are broken up by a separator character.  The default pathfield=source; sizefield=totalCount; maxcount=20; countfield=totalCount; sep="/" or "\\", depending on the operation system.

bucketdir pathfield=<field> sizefield=<field> [maxcount=<int>] [countfield=<field>] [sep=<char>]

#### Required arguments

#### Optional arguments

The bucketdir command is a streaming command. It is distributable streaming by default, but centralized streaming if the local setting specified for the command in the commands.conf file is set to true. See Command types.

#### Example 1:

Return 10 best sources and directories.

... | top source | bucketdir pathfield=source sizefield=count maxcount=10

cluster, dedup
 