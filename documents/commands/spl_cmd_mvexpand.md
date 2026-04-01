---
 command: mvexpand
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/mvexpand
 title: mvexpand
 download_date: 2026-02-03 09:12:30
---

 # mvexpand

Expands the values of a multivalue field into separate events, one event for each value in the multivalue field. For each result, the mvexpand command creates a new result for every multivalue field.

Note: The mvexpand command can't be applied to internal fields.

See Use default fields in the Knowledge Manager Manual.

mvexpand <field> [limit=<int>]

#### Required arguments

#### Optional arguments

The mvexpand command is a distributable streaming command. See Command types.

You can use evaluation functions and statistical functions on multivalue fields or to return multivalue fields.

#### Limits

A limit exists on the amount of RAM that the mvexpand command is permitted to use while expanding a batch of results. By default the limit is 500MB. The input chunk of results is typically maxresultrows or smaller in size, and the expansion of all these results resides in memory at one time. The total necessary memory is the average result size multiplied by the number of results in the chunk multiplied by the average size of the multivalue field being expanded.

If this attempt exceeds the configured maximum on any chunk, the chunk is truncated and a warning message is emitted. If you have Splunk Enterprise, you can adjust the limit by editing the max_mem_usage_mb setting in the limits.conf file.

Prerequisites

- Have the permissions to increase the maxresultrows and max_mem_usage_mb settings. Only users with file system access, such as system administrators, can increase the maxresultrows and max_mem_usage_mb settings using configuration files.
- Know how to edit configuration files. Review the steps in How to edit a configuration file in the Splunk Enterprise Admin Manual.
- Decide which directory to store configuration file changes in. There can be configuration files with the same name in your default, local, and app directories. See Where you can place (or find) your modified configuration files in the Splunk Enterprise Admin Manual.

CAUTION: Never change or copy the configuration files in the default directory. The files in the default directory must remain intact and in their original location. Make changes to the files in the local directory.

If you use Splunk Cloud Platform and encounter problems because of this limit, file a Support ticket.

#### Example 1:

Create new events for each value of multivalue field, "foo".

#### Example 2:

Create new events for the first 100 values of multivalue field, "foo".

#### Example 3:

The mvexpand command only works on one multivalue field. This example walks through how to expand an event with more than one multivalue field into individual events for each field value. For example, given these events, with sourcetype=data:

First, use the rex command to extract the field values for a and b. Then use the eval command and mvzip function to create a new field from the values of a and b.

The results appear on the Statistics tab and look something like this:

| _time | fields |
| --- | --- |
| 2018-04-01 00:11:23 | 22,21
23,32
51,24 |
| 2018-04-01 00:11:22 | 1,2
2,3
5,2 |

Use the table command to display only the _time, alpha, and beta fields in a results table.

The results appear on the Statistics tab and look something like this:

| _time | alpha | beta |
| --- | --- | --- |
| 2018-04-01 00:11:23 | 23 | 32 |
| 2018-04-01 00:11:23 | 51 | 24 |
| 2018-04-01 00:11:22 | 1 | 2 |
| 2018-04-01 00:11:22 | 2 | 3 |
| 2018-04-01 00:11:22 | 5 | 2 |

(Thanks to Splunk user Duncan for this example.)
 