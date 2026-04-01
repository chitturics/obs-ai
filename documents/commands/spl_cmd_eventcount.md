---
 command: eventcount
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/eventcount
 title: eventcount
 download_date: 2026-02-03 09:05:56
---

 # eventcount

Returns the number of events in specified indexes.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The eventcount command is a report-generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search.

Specifying a time range has no effect on the results returned by the eventcount command. All of the events on the indexes you specify are counted.

#### Specifying indexes

You cannot specify indexes to exclude from the results. For example, index!=foo is not valid syntax.

You can specify the index argument multiple times.  For example:

#### See event counts for indexes on remote Splunk platform deployments

If you use Federated Search for Splunk, you can find the count of events in specified indexes on your federated providers by running eventcount with summarize=false and list_federated_remote=true.

When you set summarize=false and list_federated_remote=true, eventcount can return event counts for specified remote indexes on federated providers to which your Splunk platform deployment is connected. The provider column identifies the federated providers that each specified remote index is associated with.

Indexes that are present on your local Splunk platform deployment have a platform value of local. Your local Splunk platform deployment is the Splunk platform deployment from which you run searches.

If you set summarize=false and do not set list_federated_remote or set list_federated_remote=false, eventcount returns event counts only for indexes on your local Splunk platform deployment.

See About Federated Search for Splunk, in Federated Search.

#### Running in clustered environments

Do not use the eventcount command to count events for comparison in indexer clustered environments. When a search runs, the eventcount command checks all buckets, including replicated and primary buckets, across all indexers in a cluster. As a result, the search may return inaccurate event counts.

#### Example 1:

Display a count of the events in the default indexes from all of the search peers.  A single count is returned.

#### Example 2:

Return the number of events in only the internal default indexes. Display the corresponding providers and servers. Include the index size, in bytes, in the results.

The results appear on the Statistics tab and will be similar to the results shown in the following table.

| count | index | provider | server | size_bytes |
| --- | --- | --- | --- | --- |
| 52550 | _audit | local | buttercup-mbpr15.sv.splunk.com | 7217152 |
| 1423010 | _internal | local | buttercup-mbpr15.sv.splunk.com | 122138624 |
| 22626 | _introspection | local | buttercup-mbpr15.sv.splunk.com | 98619392 |
| 10 | _telemetry | local | buttercup-mbpr15.sv.splunk.com | 135168 |
| 0 | _thefishbucket | local | buttercup-mbpr15.sv.splunk.com | 0 |

When you specify summarize=false, the command returns four fields: count, index, provider, and server.

When you specify report_size=true, the command returns the size_bytes field. The values in the size_bytes field are not the same as the index size on disk.

#### Example 3:

For each specified index, return an event count and its corresponding provider and server values. Filter internal indexes out of the result set.

The results appear on the Statistics tab and will be similar to the results shown in the following table.

| count | index | provider | server |
| --- | --- | --- | --- |
| 0 | history | local | sting-mba13.sv.splunk.com |
| 109864 | main | local | sting-mba13.sv.splunk.com |
| 0 | summary | local | sting-mba13.sv.splunk.com |
| 6906 | usgs_earthquake | local | sting-mba13.sv.splunk.com |

To return the count all of the indexes including the internal indexes, you must specify the internal indexes separately from the external indexes:

#### Example 4:

Return event counts for the internal indexes in your local Splunk platform deployment and the internal indexes in the remote Splunk platform deployment that is connected to your Splunk deployment as a standard mode federated provider. Filter out indexes that are not internal.

Because this search runs over a standard mode federated provider, you use the federated: syntax to specify the indexes on the federated provider.

The results appear on the Statistics tab and will be similar to the results shown in the following table.

| count | index | provider | server |
| --- | --- | --- | --- |
| 5015002 | access_combined | local | sting-mba13.sv.splunk.com |
| 4994000 | access_combined | remote01 | buttercup-mbpr15.sv.splunk.com |
| 4921285 | access_combined_wcookie | local | sting-mba13.sv.splunk.com |
| 4741874 | access_combined_wcookie | remote01 | buttercup-mbpr15.sv.splunk.com |

The search returns event counts for two access_combined indexes and two access_combined_wcookie indexes, but they are not duplicates. Your local Splunk platform deployment has indexes that share names with indexes on its remote federated provider, which is expected.

See Run federated searches over remote Splunk platform deployments, in Federated Search.

metadata,
fieldsummary
 