---
 command: dump
 source_url: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/Dump
 title: dump
 download_date: 2026-02-03 09:05:34
---

 # dump

CAUTION: The dump command is an internal, unsupported, experimental command. See 
About internal commands.

For Splunk Enterprise deployments, export search results to a set of chunk files on local disk.
For information about other export methods, see Export search results in the Search Manual.

CAUTION: This command is considered risky because, if used incorrectly, it can pose a security risk or potentially lose data when it runs. As a result, this command triggers SPL safeguards. See SPL safeguards for risky commands in Securing the Splunk Platform.

#### Syntax

Required syntax is in bold:

#### Required arguments

#### Optional arguments

This command exports events to a set of chunk files on local disk at "$SPLUNK_HOME/var/run/splunk/dispatch/<sid>/dump". This command recognizes a special field in the input events, _dstpath, which if set is used as a path to be appended to the dst directory to compute the final destination path.

The dump command preserves the order of events as the events are received by the command.

#### Capability required

The dump command is considered to be a potentially risky command. To use this command, you must have a role with the run_dump capability. See Define roles on the Splunk platform with capabilities.

For more information about risky commands, see SPL safeguards for risky commands.

Example 1: Export all events from index "bigdata" to the location "YYYYmmdd/HH/host" at "$SPLUNK_HOME/var/run/splunk/dispatch/<sid>/dump/" directory on local disk with "MyExport" as the prefix of export filenames. Partitioning of the export data is achieved by eval preceding the dump command.

Example 2: Export all events from index "bigdata" to the local disk with "MyExport" as the prefix of export filenames.

Example 3: Export all fields from events in the _internal index to the local disk with "TestAllFields" as the prefix of export filenames.
 